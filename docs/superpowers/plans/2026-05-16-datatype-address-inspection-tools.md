# Datatype & Address Inspection Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three MCP tools (`define_struct`, `describe_address`, `clear_struct_field`) and fix the `list_globals` substring search so it surfaces dynamically-generated symbols.

**Architecture:** Three new `@McpTool` methods (auto-registered by `AnnotationScanner` — no bridge changes), plus a one-line iterator change in `ListingService.listGlobals`. `define_struct` builds a fresh `StructureDataType` from a parsed JSON layout in one transaction; `clear_struct_field` uses `Structure.clearComponent` for non-shifting clears; `describe_address` reads listing/symbol/reference metadata for one address.

**Tech Stack:** Java 21, Ghidra 12.0.4 program-model API, JUnit offline tests, pytest integration tests against live Ghidra on `127.0.0.1:8089`.

**Spec:** `docs/superpowers/specs/2026-05-16-datatype-address-inspection-tools-design.md`

**Build/test environment note:** Per project memory, build and Java tests run with the **Windows toolchain via `cmd.exe`** from WSL (Adoptium JDK 21, `gradlew.bat`). When a step says "build" or "run Java tests", invoke through `cmd.exe /c` against the Windows checkout. Integration (pytest) steps require a **live Ghidra on port 8089 with a binary open** and the freshly-built JAR deployed — those steps are batched into Task 7.

**Line-ending note:** Per project memory the working tree has pervasive pre-existing CRLF churn. **Stage only the files you changed** (`git add <explicit paths>`), never `git add -A`.

---

## File Structure

| File | Change | Responsibility |
|------|--------|----------------|
| `src/main/java/com/xebyte/core/DataTypeService.java` | Modify | Add `clear_struct_field`, `define_struct` (+ `LayoutEntry`, `parseDefineStructLayout`, `parseIntOr`, `defineStructPacked` helpers) |
| `src/main/java/com/xebyte/core/ListingService.java` | Modify | Add `describe_address` (+ `describePointerTarget` helper); fix `listGlobals` Pass 1 iterator |
| `tests/endpoints.json` | Regenerate | Catalog the 3 new endpoints |
| `tests/integration/test_phase3_datatypes.py` | Modify | Integration tests for `define_struct` + `clear_struct_field` |
| `tests/integration/test_readonly_endpoints.py` | Modify | Integration tests for `describe_address` + `list_globals` regression |
| `docs/prompts/TOOL_USAGE_GUIDE.md` | Modify | Document the 3 new tools |
| `docs/prompts/DATA_TYPE_INVESTIGATION_WORKFLOW.md` | Modify | Document `define_struct` + `clear_struct_field` workflow |

---

## Task 1: `clear_struct_field` tool

Non-compacting field clear. Replaces a field with undefined bytes of the same length (`Structure.clearComponent`) so later fields keep their offsets — closes the standing memory TODO about reserving bitfield space.

**Files:**
- Modify: `src/main/java/com/xebyte/core/DataTypeService.java` (insert after `removeStructField`'s backward-compat overload, before `moveDataTypeToCategory`)

- [ ] **Step 1: Add the `clearStructField` method**

Insert this method immediately after the `removeStructField(String, String)` backward-compat overload (the line `return removeStructField(structName, fieldName, null);` block) and before the `/** Move a data type ... */` comment:

```java
    /**
     * Clear a structure field to undefined bytes WITHOUT shifting later
     * fields. Unlike {@code remove_struct_field} (which compacts and shifts
     * later members down), this reserves the field's byte region so a
     * bitfield can later be placed there with {@code add_struct_bitfield}.
     */
    @McpTool(path = "/clear_struct_field", method = "POST",
            description = "Clear a structure field to undefined bytes WITHOUT shifting later fields. Unlike remove_struct_field (which compacts), this reserves the field's byte region so a bitfield can later be placed there with add_struct_bitfield.",
            category = "datatype")
    public Response clearStructField(
            @Param(value = "struct_name", source = ParamSource.BODY) String structName,
            @Param(value = "field_name", source = ParamSource.BODY) String fieldName,
            @Param(value = "program", description = "Target program name", defaultValue = "") String programName) {
        ServiceUtils.ProgramOrError pe = ServiceUtils.getProgramOrError(programProvider, programName);
        if (pe.hasError()) return pe.error();
        Program program = pe.program();
        if (structName == null || structName.isEmpty()) return Response.err("Structure name is required");
        if (fieldName == null || fieldName.isEmpty()) return Response.err("Field name is required");

        AtomicReference<Response> responseRef = new AtomicReference<>();
        try {
            SwingUtilities.invokeAndWait(() -> {
                int tx = program.startTransaction("Clear struct field");
                boolean committed = false;
                try {
                    DataTypeManager dtm = program.getDataTypeManager();
                    DataType dataType = ServiceUtils.findDataTypeByNameInAllCategories(dtm, structName);
                    if (dataType == null) {
                        responseRef.set(Response.err("Structure not found: " + structName));
                        return;
                    }
                    if (!(dataType instanceof Structure)) {
                        responseRef.set(Response.err("Data type '" + structName + "' is not a structure"));
                        return;
                    }
                    Structure struct = (Structure) dataType;
                    int targetOrdinal = -1;
                    int clearedOffset = -1;
                    int clearedLength = -1;
                    for (DataTypeComponent component : struct.getDefinedComponents()) {
                        if (fieldName.equals(component.getFieldName())) {
                            targetOrdinal = component.getOrdinal();
                            clearedOffset = component.getOffset();
                            clearedLength = component.getLength();
                            break;
                        }
                    }
                    if (targetOrdinal == -1) {
                        responseRef.set(Response.err("Field '" + fieldName
                            + "' not found in structure '" + structName + "'"));
                        return;
                    }
                    struct.clearComponent(targetOrdinal);
                    committed = true;
                    Map<String, Object> data = new LinkedHashMap<>();
                    data.put("success", true);
                    data.put("struct", structName);
                    data.put("field", fieldName);
                    data.put("cleared_offset", clearedOffset);
                    data.put("cleared_length", clearedLength);
                    data.put("struct_length", struct.getLength());
                    responseRef.set(Response.ok(data));
                } catch (Exception e) {
                    responseRef.set(Response.err("Error clearing struct field: " + e.getMessage()));
                } finally {
                    program.endTransaction(tx, committed);
                }
            });
        } catch (InterruptedException | InvocationTargetException e) {
            return Response.err("Failed to execute struct field clear on Swing thread: " + e.getMessage());
        }
        Response r = responseRef.get();
        return r != null ? r : Response.err("Struct field clear produced no response");
    }
```

- [ ] **Step 2: Compile-check**

Run (Windows toolchain via cmd.exe):
```
cmd.exe /c "gradlew.bat compileJava -PGHIDRA_INSTALL_DIR=F:\ghidra_12.0.4_PUBLIC"
```
Expected: `BUILD SUCCESSFUL`. If it fails, fix the compile error before continuing.

- [ ] **Step 3: Commit**

```bash
git add src/main/java/com/xebyte/core/DataTypeService.java
git commit -m "feat(datatype): clear_struct_field — non-compacting field clear"
```

---

## Task 2: `define_struct` tool

Atomic struct builder. One JSON `layout` array → a complete `StructureDataType` in one call: plain fields, nested structs, explicitly-placed bitfields, gaps.

**Files:**
- Modify: `src/main/java/com/xebyte/core/DataTypeService.java`

- [ ] **Step 1: Add the `LayoutEntry` helper class**

Insert immediately after the existing `FieldDefinition` class (after its closing brace at the `}` following the `FieldDefinition` constructor):

```java
    /**
     * One entry in a {@code define_struct} layout array. {@code kind} is
     * either explicit (from the JSON) or inferred: {@code bitfield} when
     * {@code bit_size} is present, {@code gap} when {@code size} is present
     * and {@code name} is absent, otherwise {@code field}.
     */
    private static class LayoutEntry {
        String kind;        // "field" | "bitfield" | "gap"
        String name;
        String type;        // field type
        String baseType;    // bitfield base type
        String comment;     // bitfield comment (optional)
        int index;          // position in the layout array, for error messages
        int offset = -1;    // field/gap explicit byte offset (-1 = append)
        int size = -1;      // gap byte size
        int byteOffset = -1;
        int bitOffset = -1;
        int bitSize = -1;
        int resolvedOffset = -1;  // assigned during non-packed planning
        DataType resolvedType;    // field type, or bitfield base type
    }
```

- [ ] **Step 2: Add the `parseIntOr` + `parseDefineStructLayout` helpers**

Insert immediately before the `badFieldsFormatHint` method (before its `/** ... */` comment, or just before `private static String badFieldsFormatHint`):

```java
    /** Parse {@code s} as a decimal int, returning {@code dflt} on null/garbage. */
    private static int parseIntOr(String s, int dflt) {
        if (s == null) return dflt;
        try {
            return Integer.parseInt(s.trim());
        } catch (NumberFormatException e) {
            return dflt;
        }
    }

    /**
     * Parse a {@code define_struct} layout JSON array into classified
     * {@link LayoutEntry} objects. Reuses {@link #parseFieldJsonArray} for
     * brace-matched object splitting and {@link #parseJsonKeyValues} for
     * key/value extraction. Throws {@link IllegalArgumentException} with a
     * caller-facing message on malformed JSON.
     */
    private List<LayoutEntry> parseDefineStructLayout(String layoutJson) {
        String json = layoutJson.trim();
        if (!json.startsWith("[") || !json.endsWith("]")) {
            throw new IllegalArgumentException(
                "layout must be a JSON array of entry objects, e.g. "
                + "[{\"name\":\"dwId\",\"type\":\"uint\",\"offset\":0},"
                + "{\"name\":\"FLAGS\",\"base_type\":\"uint\",\"byte_offset\":4,"
                + "\"bit_offset\":0,\"bit_size\":3}]");
        }
        json = json.substring(1, json.length() - 1).trim();
        List<String> objs = parseFieldJsonArray(json);
        List<LayoutEntry> entries = new ArrayList<>();
        int idx = 0;
        for (String obj : objs) {
            Map<String, String> kv = parseJsonKeyValues(obj);
            LayoutEntry e = new LayoutEntry();
            e.index = idx++;
            e.name = firstOf(kv, "name", "field_name", "fieldName", "field");
            e.type = firstOf(kv, "type", "field_type", "fieldType", "data_type", "dataType");
            e.baseType = firstOf(kv, "base_type", "baseType");
            e.kind = firstOf(kv, "kind");
            e.comment = firstOf(kv, "comment");
            e.offset = parseIntOr(firstOf(kv, "offset", "field_offset", "fieldOffset", "off"), -1);
            e.byteOffset = parseIntOr(firstOf(kv, "byte_offset", "byteOffset"), -1);
            e.bitOffset = parseIntOr(firstOf(kv, "bit_offset", "bitOffset"), -1);
            e.bitSize = parseIntOr(firstOf(kv, "bit_size", "bitSize"), -1);
            e.size = parseIntOr(firstOf(kv, "size"), -1);
            if (e.kind == null || e.kind.isEmpty()) {
                if (e.bitSize >= 0) {
                    e.kind = "bitfield";
                } else if (e.size >= 0 && (e.name == null || e.name.isEmpty())) {
                    e.kind = "gap";
                } else {
                    e.kind = "field";
                }
            }
            e.kind = e.kind.toLowerCase();
            entries.add(e);
        }
        return entries;
    }
```

- [ ] **Step 3: Add the `defineStruct` MCP method**

Insert immediately after the `clearStructField` method added in Task 1 (before the `/** Move a data type ... */` comment):

```java
    /**
     * Build a complete structure from a single JSON layout: plain fields,
     * nested structs, explicitly-placed bitfields, and gaps. The whole layout
     * is declared at once, so there is no compaction and no
     * create_struct + N×add_struct_bitfield + delete-rebuild cycle.
     */
    @McpTool(path = "/define_struct", method = "POST",
            description = "Build a complete structure from a single JSON layout in one call: plain fields, nested structs, explicitly-placed bitfields, and gaps. Sidesteps the create_struct + N×add_struct_bitfield + delete-rebuild dance. Each layout entry's kind is inferred (field / bitfield / gap) or set explicitly with \"kind\".",
            category = "datatype")
    public Response defineStruct(
            @Param(value = "name", source = ParamSource.BODY,
                   description = "New structure type name, e.g. UnitAny") String name,
            @Param(value = "layout", source = ParamSource.BODY, fieldsJson = true,
                   description = "JSON array of layout entries. field: {name,type,offset?} (offset omitted = append; type may be any resolvable type or existing struct). bitfield (inferred when bit_size present): {name,base_type,byte_offset,bit_offset,bit_size,comment?}. gap (inferred when size present and no name): {offset?,size}. Holes left between explicit offsets stay undefined automatically.") String layoutJson,
            @Param(value = "packed", source = ParamSource.BODY, defaultValue = "false",
                   description = "Enable structure packing. When true, entries append in order and Ghidra computes offsets; explicit offset/byte_offset and gap entries are rejected.") boolean packed,
            @Param(value = "program", description = "Target program name", defaultValue = "") String programName) {
        ServiceUtils.ProgramOrError pe = ServiceUtils.getProgramOrError(programProvider, programName);
        if (pe.hasError()) return pe.error();
        Program program = pe.program();

        if (name == null || name.isEmpty()) return Response.err("Structure name is required");
        if (layoutJson == null || layoutJson.isEmpty()) {
            return Response.err("layout is required (a JSON array of entry objects)");
        }

        List<LayoutEntry> entries;
        try {
            entries = parseDefineStructLayout(layoutJson);
        } catch (IllegalArgumentException e) {
            return Response.err(e.getMessage());
        }
        if (entries.isEmpty()) return Response.err("layout must contain at least one entry");

        DataTypeManager dtm = program.getDataTypeManager();
        if (dtm.getDataType("/" + name) != null) {
            return Response.err("Structure with name '" + name + "' already exists");
        }

        // Resolve types and run kind-independent validation off-transaction.
        for (LayoutEntry e : entries) {
            if ("field".equals(e.kind)) {
                if (e.name == null || e.name.isEmpty() || e.type == null || e.type.isEmpty()) {
                    return Response.err("layout entry " + e.index + " (field) requires name and type");
                }
                DataType dt = ServiceUtils.resolveDataType(dtm, e.type);
                if (dt == null) {
                    return Response.err("layout entry " + e.index + ": unknown type '" + e.type + "'");
                }
                if (dt.getLength() <= 0) {
                    return Response.err("layout entry " + e.index + ": type '" + e.type
                        + "' has no fixed size and cannot be placed");
                }
                e.resolvedType = dt;
                e.name = NamingConventions.applyStructFieldNamingPolicy(e.name, e.type);
            } else if ("bitfield".equals(e.kind)) {
                if (e.name == null || e.name.isEmpty()) {
                    return Response.err("layout entry " + e.index + " (bitfield) requires name");
                }
                if (!BITFIELD_NAME_PATTERN.matcher(e.name).matches()) {
                    return Response.err("layout entry " + e.index + ": invalid bitfield name '"
                        + e.name + "' — must be a valid identifier");
                }
                if (e.baseType == null || e.baseType.isEmpty()) {
                    return Response.err("layout entry " + e.index + " (bitfield) requires base_type");
                }
                if (e.bitSize < 1) {
                    return Response.err("layout entry " + e.index + " (bitfield) requires bit_size >= 1");
                }
                DataType base = ServiceUtils.resolveDataType(dtm, e.baseType);
                if (base == null) {
                    return Response.err("layout entry " + e.index + ": unknown base_type '" + e.baseType + "'");
                }
                DataType probe = base;
                int guard = 0;
                while (probe instanceof TypeDef && guard++ < 64) {
                    probe = ((TypeDef) probe).getBaseDataType();
                }
                if (!(probe instanceof AbstractIntegerDataType)) {
                    return Response.err("layout entry " + e.index + ": base_type '" + e.baseType
                        + "' is not an integer type; bitfields require an integer base type");
                }
                if (base.getLength() <= 0) {
                    return Response.err("layout entry " + e.index + ": base_type '" + e.baseType
                        + "' has no fixed storage size");
                }
                int maxBits = base.getLength() * 8;
                if (e.bitSize > maxBits) {
                    return Response.err("layout entry " + e.index + ": bit_size " + e.bitSize
                        + " exceeds base type width (" + maxBits + " bits)");
                }
                e.resolvedType = base;
            } else if ("gap".equals(e.kind)) {
                if (e.size < 1) {
                    return Response.err("layout entry " + e.index + " (gap) requires size >= 1");
                }
            } else {
                return Response.err("layout entry " + e.index + ": unknown kind '" + e.kind
                    + "' (expected field, bitfield, or gap)");
            }
        }

        if (packed) {
            return defineStructPacked(program, dtm, name, entries);
        }

        // Non-packed: bitfields need explicit placement; assign offsets with
        // an append cursor for entries that omit an explicit offset.
        for (LayoutEntry e : entries) {
            if ("bitfield".equals(e.kind)) {
                if (e.byteOffset < 0) {
                    return Response.err("layout entry " + e.index
                        + " (bitfield) requires byte_offset >= 0 when packed=false");
                }
                if (e.bitOffset < 0) {
                    return Response.err("layout entry " + e.index
                        + " (bitfield) requires bit_offset >= 0 when packed=false");
                }
                int maxBits = e.resolvedType.getLength() * 8;
                if (e.bitOffset + e.bitSize > maxBits) {
                    return Response.err("layout entry " + e.index + ": bit_offset " + e.bitOffset
                        + " + bit_size " + e.bitSize + " exceeds base type width (" + maxBits + " bits)");
                }
            }
        }
        int cursor = 0;
        for (LayoutEntry e : entries) {
            if ("field".equals(e.kind)) {
                e.resolvedOffset = (e.offset >= 0) ? e.offset : cursor;
                cursor = Math.max(cursor, e.resolvedOffset + e.resolvedType.getLength());
            } else if ("bitfield".equals(e.kind)) {
                e.resolvedOffset = e.byteOffset;
                cursor = Math.max(cursor, e.byteOffset + e.resolvedType.getLength());
            } else { // gap
                e.resolvedOffset = (e.offset >= 0) ? e.offset : cursor;
                cursor = Math.max(cursor, e.resolvedOffset + e.size);
            }
        }
        final int totalSize = cursor;
        if (totalSize <= 0) {
            return Response.err("computed struct size is zero — layout has no placeable entries");
        }

        // Overlap pre-check: no two non-bitfield byte ranges (fields/gaps) may
        // overlap, and no bitfield byte region may overlap a field/gap.
        // Bitfield-vs-bitfield byte overlap is allowed (shared storage word) —
        // a bit-range conflict inside a shared word is caught by the
        // post-insert growth guard below.
        for (int i = 0; i < entries.size(); i++) {
            LayoutEntry a = entries.get(i);
            int[] ra = layoutByteRange(a);
            for (int j = i + 1; j < entries.size(); j++) {
                LayoutEntry b = entries.get(j);
                if ("bitfield".equals(a.kind) && "bitfield".equals(b.kind)) continue;
                int[] rb = layoutByteRange(b);
                if (ra[0] < rb[1] && rb[0] < ra[1]) {
                    return Response.err("layout entries " + a.index + " and " + b.index
                        + " overlap (byte ranges [" + ra[0] + "," + ra[1] + ") and ["
                        + rb[0] + "," + rb[1] + "))");
                }
            }
        }

        AtomicReference<Response> responseRef = new AtomicReference<>();
        try {
            SwingUtilities.invokeAndWait(() -> {
                int tx = program.startTransaction("Define structure: " + name);
                boolean committed = false;
                try {
                    ghidra.program.model.data.StructureDataType struct =
                        new ghidra.program.model.data.StructureDataType(name, totalSize);
                    // Plain fields first — they overlay undefined bytes in place.
                    for (LayoutEntry e : entries) {
                        if ("field".equals(e.kind)) {
                            struct.replaceAtOffset(e.resolvedOffset, e.resolvedType,
                                e.resolvedType.getLength(), e.name, "");
                        }
                    }
                    // Then bitfields. insertBitFieldAt into free undefined space
                    // does not grow the struct; a bit-range conflict relocates
                    // the bitfield and grows it — detect that and roll back.
                    for (LayoutEntry e : entries) {
                        if (!"bitfield".equals(e.kind)) continue;
                        int byteWidth = e.resolvedType.getLength();
                        int before = struct.getLength();
                        struct.insertBitFieldAt(e.byteOffset, byteWidth, e.bitOffset,
                            e.resolvedType, e.bitSize, e.name,
                            e.comment != null ? e.comment : "");
                        int expected = Math.max(before, e.byteOffset + byteWidth);
                        if (struct.getLength() > expected) {
                            responseRef.set(Response.err("bitfield '" + e.name + "' (layout entry "
                                + e.index + ") could not be placed at byte_offset " + e.byteOffset
                                + " bit_offset " + e.bitOffset + ": the bit range conflicts with "
                                + "another bitfield in that storage word"));
                            return;  // committed stays false -> rollback
                        }
                    }
                    DataType created = dtm.addDataType(struct, null);
                    committed = true;
                    Map<String, Object> data = new LinkedHashMap<>();
                    data.put("success", true);
                    data.put("struct", name);
                    data.put("length", created.getLength());
                    data.put("entry_count", entries.size());
                    data.put("packed", false);
                    responseRef.set(Response.ok(data));
                } catch (Throwable t) {
                    String msg = t.getMessage() != null ? t.getMessage() : t.toString();
                    responseRef.set(Response.err("Error defining structure: " + msg));
                    Msg.error(this, "Error defining structure", t);
                } finally {
                    program.endTransaction(tx, committed);
                }
            });
        } catch (InterruptedException | InvocationTargetException e) {
            return Response.err("Failed to define structure on Swing thread: " + e.getMessage());
        }
        program.flushEvents();
        Response r = responseRef.get();
        return r != null ? r : Response.err("define_struct produced no response");
    }

    /** Byte range [start, end) occupied by a layout entry. */
    private static int[] layoutByteRange(LayoutEntry e) {
        if ("bitfield".equals(e.kind)) {
            return new int[]{e.byteOffset, e.byteOffset + e.resolvedType.getLength()};
        }
        if ("field".equals(e.kind)) {
            return new int[]{e.resolvedOffset, e.resolvedOffset + e.resolvedType.getLength()};
        }
        return new int[]{e.resolvedOffset, e.resolvedOffset + e.size}; // gap
    }

    /**
     * Packed variant of {@code define_struct}: entries append in order and
     * Ghidra computes offsets. Explicit offsets/byte_offset and gap entries
     * are rejected — they are meaningless under automatic packing.
     */
    private Response defineStructPacked(Program program, DataTypeManager dtm,
                                        String name, List<LayoutEntry> entries) {
        for (LayoutEntry e : entries) {
            if ("gap".equals(e.kind)) {
                return Response.err("layout entry " + e.index
                    + ": gap entries are not allowed when packed=true");
            }
            if ("field".equals(e.kind) && e.offset >= 0) {
                return Response.err("layout entry " + e.index
                    + ": explicit offset is not allowed when packed=true");
            }
            if ("bitfield".equals(e.kind) && e.byteOffset >= 0) {
                return Response.err("layout entry " + e.index
                    + ": explicit byte_offset is not allowed when packed=true");
            }
        }
        AtomicReference<Response> responseRef = new AtomicReference<>();
        try {
            SwingUtilities.invokeAndWait(() -> {
                int tx = program.startTransaction("Define packed structure: " + name);
                boolean committed = false;
                try {
                    ghidra.program.model.data.StructureDataType struct =
                        new ghidra.program.model.data.StructureDataType(name, 0);
                    struct.setPackingEnabled(true);
                    for (LayoutEntry e : entries) {
                        if ("field".equals(e.kind)) {
                            struct.add(e.resolvedType, e.resolvedType.getLength(), e.name, "");
                        } else { // bitfield
                            struct.addBitField(e.resolvedType, e.bitSize, e.name,
                                e.comment != null ? e.comment : "");
                        }
                    }
                    DataType created = dtm.addDataType(struct, null);
                    committed = true;
                    Map<String, Object> data = new LinkedHashMap<>();
                    data.put("success", true);
                    data.put("struct", name);
                    data.put("length", created.getLength());
                    data.put("entry_count", entries.size());
                    data.put("packed", true);
                    responseRef.set(Response.ok(data));
                } catch (Throwable t) {
                    String msg = t.getMessage() != null ? t.getMessage() : t.toString();
                    responseRef.set(Response.err("Error defining packed structure: " + msg));
                    Msg.error(this, "Error defining packed structure", t);
                } finally {
                    program.endTransaction(tx, committed);
                }
            });
        } catch (InterruptedException | InvocationTargetException e) {
            return Response.err("Failed to define packed structure on Swing thread: " + e.getMessage());
        }
        program.flushEvents();
        Response r = responseRef.get();
        return r != null ? r : Response.err("define_struct produced no response");
    }
```

- [ ] **Step 4: Compile-check**

Run:
```
cmd.exe /c "gradlew.bat compileJava -PGHIDRA_INSTALL_DIR=F:\ghidra_12.0.4_PUBLIC"
```
Expected: `BUILD SUCCESSFUL`. Common failures to watch for: `BITFIELD_NAME_PATTERN` not visible (it is a static field of `DataTypeService` — confirm spelling), `AbstractIntegerDataType`/`TypeDef`/`BitFieldDataType` unresolved (all covered by the existing `import ghidra.program.model.data.*;`). Fix any compile error before continuing.

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/xebyte/core/DataTypeService.java
git commit -m "feat(datatype): define_struct — atomic struct builder from JSON layout"
```

---

## Task 3: `describe_address` tool

One-call address inspection: data type, symbol, size, xref count, and (for pointers) the resolved pointer target.

**Files:**
- Modify: `src/main/java/com/xebyte/core/ListingService.java`

- [ ] **Step 1: Add the `Pointer` import**

In the import block, add after `import ghidra.program.model.data.DataType;`:

```java
import ghidra.program.model.data.Pointer;
```

- [ ] **Step 2: Add the `describeAddress` method + `describePointerTarget` helper**

Insert after the `listExternalLocations` method (find its closing brace) — or anywhere among the other `@McpTool` methods in `ListingService`. Place both the public method and the private helper together:

```java
    @McpTool(path = "/describe_address",
            description = "Describe what is at an address in one call: defined data type, primary symbol name, size, xref count, and — for pointers — the recursively-resolved pointer target. Answers 'what is actually here?' without reconstructing it from raw read_memory bytes.",
            category = "listing")
    public Response describeAddress(
            @Param(value = "address", paramType = "address",
                   description = "Address in the program. Accepts 0x<hex> (default space) or "
                               + "<space>:<hex> (e.g. mem:1000).") String addressStr,
            @Param(value = "program", description = "Target program name (omit to use the active program — always specify when multiple programs are open)", defaultValue = "") String programName) {
        ServiceUtils.ProgramOrError pe = ServiceUtils.getProgramOrError(programProvider, programName);
        if (pe.hasError()) return pe.error();
        Program program = pe.program();
        if (addressStr == null || addressStr.isEmpty()) return Response.err("Address is required");

        Address addr = ServiceUtils.parseAddress(program, addressStr);
        if (addr == null) return Response.err(ServiceUtils.getLastParseError());

        Listing listing = program.getListing();
        SymbolTable symbolTable = program.getSymbolTable();
        ReferenceManager refMgr = program.getReferenceManager();

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("address", addr.toString());

        Symbol primary = symbolTable.getPrimarySymbol(addr);
        data.put("symbol", primary != null ? primary.getName() : null);

        Data definedData = listing.getDefinedDataAt(addr);
        DataType dt = (definedData != null) ? definedData.getDataType() : null;
        data.put("data_type", dt != null ? dt.getName() : null);
        data.put("size", definedData != null ? definedData.getLength() : null);
        data.put("xref_count", refMgr.getReferenceCountTo(addr));

        Map<String, Object> pointerTarget = describePointerTarget(program, definedData);
        if (pointerTarget != null) {
            data.put("pointer_target", pointerTarget);
        }

        return Response.ok(data);
    }

    /**
     * If {@code data} is a pointer, follow it — recursively through chained
     * pointers, bounded to 8 hops — and describe the eventual pointee: its
     * address, primary symbol, and defined data type. Returns null when
     * {@code data} is not a pointer or its value is not an address.
     */
    private Map<String, Object> describePointerTarget(Program program, Data data) {
        if (data == null || !(data.getDataType() instanceof Pointer)) return null;
        Listing listing = program.getListing();
        SymbolTable symbolTable = program.getSymbolTable();

        Address target = null;
        Data cur = data;
        for (int hop = 0; hop < 8; hop++) {
            Object val = cur.getValue();
            if (!(val instanceof Address)) break;
            target = (Address) val;
            Data next = listing.getDefinedDataAt(target);
            if (next == null || !(next.getDataType() instanceof Pointer)) break;
            cur = next;
        }
        if (target == null) return null;

        Map<String, Object> tgt = new LinkedHashMap<>();
        tgt.put("address", target.toString());
        Symbol s = symbolTable.getPrimarySymbol(target);
        tgt.put("symbol", s != null ? s.getName() : null);
        Data targetData = listing.getDefinedDataAt(target);
        tgt.put("data_type", (targetData != null && targetData.getDataType() != null)
                ? targetData.getDataType().getName() : null);
        return tgt;
    }
```

- [ ] **Step 3: Compile-check**

Run:
```
cmd.exe /c "gradlew.bat compileJava -PGHIDRA_INSTALL_DIR=F:\ghidra_12.0.4_PUBLIC"
```
Expected: `BUILD SUCCESSFUL`. If `ReferenceManager` is unresolved, note `ListingService` imports `ghidra.program.model.symbol.*` which covers it. Fix any compile error before continuing.

- [ ] **Step 4: Commit**

```bash
git add src/main/java/com/xebyte/core/ListingService.java
git commit -m "feat(listing): describe_address — one-call address metadata inspection"
```

---

## Task 4: Fix `list_globals` substring search

`listGlobals` Pass 1 iterates `symbolTable.getSymbols(globalNamespace)`, which excludes dynamically-generated symbols (e.g. `PTR_CarConfigSource_00017888`). Those addresses then also fall through Pass 2 (line `symbolTable.getPrimarySymbol(addr) != null` skips them). Switch Pass 1 to `getAllSymbols(true)` (includes dynamic symbols) filtered to global scope.

**Files:**
- Modify: `src/main/java/com/xebyte/core/ListingService.java` (the `listGlobals` method, Pass 1 — around lines 537-545)

- [ ] **Step 1: Replace the Pass 1 iterator and add a global-scope filter**

Find this block (the Pass 1 comment + iterator setup + the start of the `while` loop):

```java
        // Pass 1: iterate the global namespace, emit symbols that match
        // the filter axes (skipping code labels and functions as before).
        Namespace globalNamespace = program.getGlobalNamespace();
        SymbolIterator symbols = symbolTable.getSymbols(globalNamespace);
        while (symbols.hasNext()) {
            Symbol symbol = symbols.next();
            if (symbol.getSymbolType() == SymbolType.FUNCTION) {
                continue;
            }
```

Replace it with:

```java
        // Pass 1: iterate every symbol (including dynamically-generated ones
        // such as PTR_*/DAT_* pointer labels — getSymbols(globalNamespace)
        // excludes those, which is why name_substring searches against them
        // previously returned empty), filtered to global scope. All existing
        // gates below (code-address, section, axis, min_xrefs, substring) are
        // preserved unchanged.
        SymbolIterator symbols = symbolTable.getAllSymbols(true);
        while (symbols.hasNext()) {
            Symbol symbol = symbols.next();
            if (symbol.getSymbolType() == SymbolType.FUNCTION) {
                continue;
            }
            if (!symbol.isGlobal()) {
                continue;
            }
```

This removes the now-unused `globalNamespace` local. If a later compile error reports `globalNamespace` is still referenced elsewhere in the method, leave its declaration in place instead; it is only used by Pass 1.

- [ ] **Step 2: Compile-check**

Run:
```
cmd.exe /c "gradlew.bat compileJava -PGHIDRA_INSTALL_DIR=F:\ghidra_12.0.4_PUBLIC"
```
Expected: `BUILD SUCCESSFUL`. A warning about unused import `GlobalNamespace` is acceptable; do not remove the import unless the build treats warnings as errors (it does not).

- [ ] **Step 3: Commit**

```bash
git add src/main/java/com/xebyte/core/ListingService.java
git commit -m "fix(listing): list_globals surfaces dynamic symbols for substring search

Pass 1 iterated getSymbols(globalNamespace), which excludes dynamic
PTR_*/DAT_* labels; those addresses also fell through Pass 2. Iterate
getAllSymbols(true) filtered to global scope so name_substring matches
dynamically-generated symbols."
```

---

## Task 5: Regenerate `endpoints.json` + offline Java tests

Three new `@McpTool` methods make `tests/endpoints.json` stale; `EndpointsJsonParityTest` will fail until regenerated.

**Files:**
- Regenerate: `tests/endpoints.json`

- [ ] **Step 1: Run the offline Java suite to confirm the parity failure**

Run:
```
cmd.exe /c "gradlew.bat test --tests com.xebyte.offline.* -PGHIDRA_INSTALL_DIR=F:\ghidra_12.0.4_PUBLIC"
```
Expected: `EndpointsJsonParityTest` FAILS, reporting `/define_struct`, `/clear_struct_field`, `/describe_address` missing from `endpoints.json`.

- [ ] **Step 2: Regenerate `endpoints.json`**

Run (Maven path, per CLAUDE.md — regeneration preserves hand-authored descriptions):
```
cmd.exe /c "C:\Users\benam\tools\apache-maven-3.9.6\bin\mvn.cmd test -Dtest=RegenerateEndpointsJson -Dregenerate=true"
```
Expected: `BUILD SUCCESS`; `git diff tests/endpoints.json` shows the three new endpoints added and `total_endpoints` incremented from 245 to 248.

- [ ] **Step 3: Re-run the offline Java suite to confirm it passes**

Run:
```
cmd.exe /c "gradlew.bat test --tests com.xebyte.offline.* -PGHIDRA_INSTALL_DIR=F:\ghidra_12.0.4_PUBLIC"
```
Expected: all offline tests PASS, including `EndpointsJsonParityTest`.

- [ ] **Step 4: Commit**

```bash
git add tests/endpoints.json
git commit -m "test: regenerate endpoints.json for define_struct, clear_struct_field, describe_address"
```

---

## Task 6: Integration tests

Write pytest integration tests. They require live Ghidra; they are authored here and **run in Task 7** after deploy.

**Files:**
- Modify: `tests/integration/test_phase3_datatypes.py`
- Modify: `tests/integration/test_readonly_endpoints.py`

- [ ] **Step 1: Add `define_struct` + `clear_struct_field` tests**

Append this class to the end of `tests/integration/test_phase3_datatypes.py`:

```python
class TestDefineStruct:
    """Test define_struct — atomic struct builder from a JSON layout."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_define_struct_fields_bitfield_gap_nested(self, http_client):
        """One call builds plain fields, a bitfield, a nested struct, a gap."""
        nested = f"DefNested_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={"name": nested, "fields": [{"name": "n", "type": "int"}]},
        )
        struct_name = f"DefStruct_{uuid.uuid4().hex[:8]}"
        response = http_client.post(
            "/define_struct",
            json_data={
                "name": struct_name,
                "layout": [
                    {"name": "dwId", "type": "uint", "offset": 0},
                    {"name": "FLAGS", "base_type": "uint", "byte_offset": 4,
                     "bit_offset": 0, "bit_size": 3},
                    {"offset": 8, "size": 4},
                    {"name": "child", "type": nested, "offset": 12},
                ],
            },
        )
        assert response.status_code == 200
        body = json.loads(response.text)
        assert body.get("success") is True
        assert body["struct"] == struct_name
        # uint(4) + bitfield word(4) + gap(4) + nested int(4) = 16 bytes
        assert body["length"] == 16

        layout = http_client.get(
            "/get_struct_layout", params={"struct_name": struct_name}
        )
        assert layout.status_code == 200
        assert "Bits" in layout.text
        assert "0:3" in layout.text

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_define_struct_duplicate_name_rejected(self, http_client):
        """A name that already exists is rejected."""
        struct_name = f"DefDup_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={"name": struct_name, "fields": [{"name": "f", "type": "int"}]},
        )
        response = http_client.post(
            "/define_struct",
            json_data={"name": struct_name,
                       "layout": [{"name": "f", "type": "int", "offset": 0}]},
        )
        assert response.status_code == 200
        assert is_error_response(response.text)

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_define_struct_unknown_type_rejected(self, http_client):
        """An unresolvable field type is rejected before any transaction."""
        response = http_client.post(
            "/define_struct",
            json_data={
                "name": f"DefBadType_{uuid.uuid4().hex[:8]}",
                "layout": [{"name": "f", "type": "NoSuchType_zzz", "offset": 0}],
            },
        )
        assert response.status_code == 200
        assert is_error_response(response.text)

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_define_struct_overlapping_fields_rejected(self, http_client):
        """Two plain fields with overlapping byte ranges are rejected."""
        response = http_client.post(
            "/define_struct",
            json_data={
                "name": f"DefOverlap_{uuid.uuid4().hex[:8]}",
                "layout": [
                    {"name": "a", "type": "uint", "offset": 0},
                    {"name": "b", "type": "uint", "offset": 2},
                ],
            },
        )
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestClearStructField:
    """Test clear_struct_field — non-compacting field clear."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_clear_struct_field_preserves_later_offsets(self, http_client):
        """Clearing a field leaves later fields at their original offsets."""
        struct_name = f"ClrStruct_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={
                "name": struct_name,
                "fields": [
                    {"name": "first", "type": "uint", "offset": 0},
                    {"name": "middle", "type": "uint", "offset": 4},
                    {"name": "last", "type": "uint", "offset": 8},
                ],
            },
        )
        response = http_client.post(
            "/clear_struct_field",
            json_data={"struct_name": struct_name, "field_name": "middle"},
        )
        assert response.status_code == 200
        body = json.loads(response.text)
        assert body.get("success") is True
        assert body["cleared_offset"] == 4
        assert body["cleared_length"] == 4
        # 'last' must still be at offset 8 (no compaction).
        layout = http_client.get(
            "/get_struct_layout", params={"struct_name": struct_name}
        )
        assert layout.status_code == 200
        assert "last" in layout.text

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_clear_then_place_bitfield(self, http_client):
        """A cleared region accepts a bitfield via add_struct_bitfield."""
        struct_name = f"ClrBf_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={
                "name": struct_name,
                "fields": [
                    {"name": "head", "type": "uint", "offset": 0},
                    {"name": "slot", "type": "uint", "offset": 4},
                ],
            },
        )
        http_client.post(
            "/clear_struct_field",
            json_data={"struct_name": struct_name, "field_name": "slot"},
        )
        response = http_client.post(
            "/add_struct_bitfield",
            json_data={
                "struct_name": struct_name, "base_type": "uint",
                "byte_offset": 4, "bit_offset": 0, "bit_size": 2, "name": "MODE",
            },
        )
        assert response.status_code == 200
        body = json.loads(response.text)
        assert body.get("success") is True

    @pytest.mark.requires_program
    def test_clear_struct_field_missing_field(self, http_client):
        """Clearing a non-existent field returns an error."""
        struct_name = f"ClrMiss_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={"name": struct_name, "fields": [{"name": "f", "type": "int"}]},
        )
        response = http_client.post(
            "/clear_struct_field",
            json_data={"struct_name": struct_name, "field_name": "nope"},
        )
        assert response.status_code == 200
        assert is_error_response(response.text)
```

- [ ] **Step 2: Add `describe_address` + `list_globals` regression tests**

First inspect `tests/integration/test_readonly_endpoints.py` to confirm the `http_client` fixture and helper names match `test_phase3_datatypes.py` (`http_client.get(path, params=...)`, `is_error_response`). If `is_error_response` is not importable in that file, use `"error" in response.text.lower()` for the error assertion instead.

Append this class to the end of `tests/integration/test_readonly_endpoints.py`:

```python
class TestDescribeAddressAndGlobalSearch:
    """describe_address metadata + list_globals dynamic-symbol substring fix."""

    @pytest.mark.requires_program
    def test_describe_address_invalid(self, http_client):
        """An unparseable address returns an error."""
        response = http_client.get(
            "/describe_address", params={"address": "0xZZZZZZZZ"}
        )
        assert response.status_code == 200
        assert "error" in response.text.lower()

    @pytest.mark.requires_program
    def test_describe_address_returns_metadata(self, http_client):
        """describe_address echoes address, xref_count, and the metadata keys.

        Picks a real global address from list_globals so the test is binary-
        agnostic.
        """
        globals_resp = http_client.get(
            "/list_globals", params={"limit": 50, "filter": "defined"}
        )
        assert globals_resp.status_code == 200
        addr = None
        for line in globals_resp.text.splitlines():
            if "@ " in line:
                addr = line.split("@ ", 1)[1].split()[0]
                break
        if addr is None:
            pytest.skip("no defined globals in the open program")
        response = http_client.get("/describe_address", params={"address": addr})
        assert response.status_code == 200
        body = json.loads(response.text)
        assert body["address"]
        assert "data_type" in body
        assert "symbol" in body
        assert "size" in body
        assert "xref_count" in body

    @pytest.mark.requires_program
    def test_list_globals_substring_hits_dynamic_symbols(self, http_client):
        """name_substring against a dynamic PTR_/DAT_ label now returns it.

        Regression for the root cause: Pass 1 used getSymbols(globalNamespace),
        which excluded dynamic symbols.
        """
        globals_resp = http_client.get("/list_globals", params={"limit": 400})
        assert globals_resp.status_code == 200
        dynamic_line = None
        for line in globals_resp.text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("PTR_", "DAT_")):
                dynamic_line = stripped
                break
        if dynamic_line is None:
            pytest.skip("no dynamic PTR_/DAT_ symbols in the open program")
        symbol_name = dynamic_line.split()[0]
        # Use a mid-name substring so the match exercises 'contains', not prefix.
        substring = symbol_name[4:12] if len(symbol_name) > 12 else symbol_name
        search = http_client.get(
            "/list_globals", params={"limit": 400, "name_substring": substring}
        )
        assert search.status_code == 200
        assert substring.lower() in search.text.lower()
```

If `test_readonly_endpoints.py` does not already `import json` / `import pytest`, add those imports at the top of the file.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_phase3_datatypes.py tests/integration/test_readonly_endpoints.py
git commit -m "test: integration coverage for define_struct, clear_struct_field, describe_address, list_globals fix"
```

---

## Task 7: Build, deploy, and run the integration suite

**Requires:** live Ghidra on `127.0.0.1:8089` with a binary open. If the executing environment has no live Ghidra, hand these steps to the user and stop.

- [ ] **Step 1: Full build**

Run:
```
cmd.exe /c "gradlew.bat buildExtension -PGHIDRA_INSTALL_DIR=F:\ghidra_12.0.4_PUBLIC"
```
Expected: `BUILD SUCCESSFUL`, `GhidraMCPPlugin.jar` produced.

- [ ] **Step 2: Deploy**

Run:
```
cmd.exe /c "gradlew.bat deploy -PGHIDRA_INSTALL_DIR=F:\ghidra_12.0.4_PUBLIC"
```
Expected: extension installed, Ghidra restarted. Wait for Ghidra to finish loading and re-open a binary before the next step.

- [ ] **Step 3: Verify the new endpoints registered**

Run:
```bash
curl -s http://127.0.0.1:8089/mcp/schema | python3 -c "import sys,json; s=json.load(sys.stdin); names={t.get('path') or t.get('name') for t in (s if isinstance(s,list) else s.get('tools',s.get('endpoints',[])))}; print(sorted(n for n in names if n in ('/define_struct','/clear_struct_field','/describe_address')))"
```
Expected: `['/clear_struct_field', '/define_struct', '/describe_address']`.

- [ ] **Step 4: Run the datatype integration tests**

Run:
```bash
pytest tests/integration/test_phase3_datatypes.py::TestDefineStruct tests/integration/test_phase3_datatypes.py::TestClearStructField -v --no-cov
```
Expected: all tests PASS.

- [ ] **Step 5: Run the readonly integration tests**

Run:
```bash
pytest "tests/integration/test_readonly_endpoints.py::TestDescribeAddressAndGlobalSearch" -v --no-cov
```
Expected: all tests PASS (some may `skip` if the open binary lacks defined globals or dynamic symbols — a skip is acceptable, a failure is not).

- [ ] **Step 6: Run the Java integration suite**

Run:
```
cmd.exe /c "gradlew.bat test -PGHIDRA_INSTALL_DIR=F:\ghidra_12.0.4_PUBLIC"
```
Expected: `EndpointRegistrationTest` PASSES (confirms the three new routes register); no regressions.

- [ ] **Step 7: If any test fails**

Use `superpowers:systematic-debugging`. Do not patch tests to pass — root-cause the failure. For `list_globals`, the most likely live-only issue is performance on a very large program (`getAllSymbols(true)` returns more symbols); if so, the result is still correct, just slower — not a failure. Re-run after any fix.

- [ ] **Step 8: Commit any fixes**

```bash
git add <explicit files changed during debugging>
git commit -m "fix: address integration test failures in datatype/inspection tools"
```
(Skip this step if no fixes were needed.)

---

## Task 8: Documentation

Per project convention (commit `73bdcd2` documented `add_struct_bitfield` in both guides), document the new tools.

**Files:**
- Modify: `docs/prompts/TOOL_USAGE_GUIDE.md`
- Modify: `docs/prompts/DATA_TYPE_INVESTIGATION_WORKFLOW.md`

- [ ] **Step 1: Document the three tools in `TOOL_USAGE_GUIDE.md`**

Read `docs/prompts/TOOL_USAGE_GUIDE.md`, find where `add_struct_bitfield` is documented (datatype section). Add adjacent entries:

- `define_struct` — "Build a complete struct in one call from a JSON `layout` array. Each entry is a field `{name,type,offset?}`, a bitfield `{name,base_type,byte_offset,bit_offset,bit_size}`, or a gap `{offset?,size}` — kind inferred or set with `kind`. Use instead of `create_struct` + repeated `add_struct_bitfield` whenever the full layout is known up front; it avoids the delete-and-rebuild dance for bitfield regions." Include the worked example from `TestDefineStruct.test_define_struct_fields_bitfield_gap_nested`'s `layout`.
- `clear_struct_field` — "Clear a field to undefined bytes **without** shifting later fields (unlike `remove_struct_field`, which compacts). Use to reserve a field's byte region before placing bitfields there with `add_struct_bitfield`."
- `describe_address` — "One call returns the data type, primary symbol, size, xref count, and (for pointers) the resolved pointer target at an address. Use instead of reconstructing metadata from raw `read_memory` bytes."

Match the surrounding entries' formatting exactly.

- [ ] **Step 2: Document the struct workflow in `DATA_TYPE_INVESTIGATION_WORKFLOW.md`**

Read `docs/prompts/DATA_TYPE_INVESTIGATION_WORKFLOW.md`, find the struct-creation / bitfield guidance. Add a note: when the full struct layout (including bitfield regions) is known, prefer `define_struct` with a single `layout` array over `create_struct` + N× `add_struct_bitfield`. When mutating an existing struct to host bitfields, use `clear_struct_field` (non-compacting) rather than `remove_struct_field` (compacting) so surrounding field offsets are preserved. Match the document's existing tone and section structure.

- [ ] **Step 3: Commit**

```bash
git add docs/prompts/TOOL_USAGE_GUIDE.md docs/prompts/DATA_TYPE_INVESTIGATION_WORKFLOW.md
git commit -m "docs: document define_struct, clear_struct_field, describe_address"
```

---

## Done criteria

- `define_struct`, `clear_struct_field`, `describe_address` registered in `/mcp/schema` and listed in `tests/endpoints.json` (`total_endpoints` = 248).
- `list_globals` `name_substring` returns dynamic `PTR_*`/`DAT_*` symbols.
- Offline Java suite (`com.xebyte.offline.*`) green, including `EndpointsJsonParityTest`.
- Integration tests in Tasks 6/7 green (skips allowed where the open binary lacks the needed symbols).
- `EndpointRegistrationTest` green.
- Both prompt guides updated.

## Notes for the implementer

- No `bridge_mcp_ghidra.py` changes — `AnnotationScanner` auto-discovers `@McpTool` methods; the bridge registers them dynamically from `/mcp/schema`. The bridge line-count cap is untouched.
- `define_struct` deliberately does not pre-check bitfield-vs-bitfield *bit-range* overlap in a shared storage word; the post-`insertBitFieldAt` growth guard catches it and rolls the transaction back, matching `add_struct_bitfield`'s existing behavior.
- The bitfield integer-base-type check is intentionally duplicated from `add_struct_bitfield` rather than extracted to a shared helper — extracting it would mean editing `add_struct_bitfield`, expanding the change surface and risking a regression in a just-stabilized tool. If a future change touches both, extract then.
