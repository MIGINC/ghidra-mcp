# Bitfield MCP Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `add_struct_bitfield` MCP tool that defines explicitly-placed bitfield struct members, plus a `get_struct_layout` read-back column, so the Ghidra 12.1 decompiler can recover bitfields by name.

**Architecture:** One new `@McpTool` method on `DataTypeService.java` wrapping `Structure.insertBitFieldAt`; storage byte width is derived from the base type. `get_struct_layout` gains a `Bits` column. The MCP bridge auto-registers the tool from `/mcp/schema` — no bridge code change.

**Tech Stack:** Java 21, Ghidra 12.0.x/12.1 plugin API, Gradle build, pytest integration tests.

**Spec:** `docs/superpowers/specs/2026-05-15-bitfield-tooling-design.md`

---

## Environment & Commands

This repo builds with the **Windows-side toolchain** invoked from WSL via `cmd.exe`
(the WSL Linux side has no working JDK; Maven is not installed). Use these exact
commands:

- **Compile check:**
  ```bash
  cmd.exe /c 'set "JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-21.0.6.7-hotspot" && gradlew.bat compileJava -PGHIDRA_INSTALL_DIR=C:\Ghidra\ghidra_12.1_PUBLIC --console=plain'
  ```
- **Offline Java tests (scanner + endpoints.json parity):**
  ```bash
  cmd.exe /c 'set "JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-21.0.6.7-hotspot" && gradlew.bat test --tests "com.xebyte.offline.*" -PGHIDRA_INSTALL_DIR=C:\Ghidra\ghidra_12.1_PUBLIC --console=plain'
  ```
- **Build + deploy the extension** (close Ghidra first):
  ```bash
  cmd.exe /c 'set "JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-21.0.6.7-hotspot" && gradlew.bat deploy -PGHIDRA_INSTALL_DIR=C:\Ghidra\ghidra_12.1_PUBLIC --console=plain'
  ```
- **Integration tests** (requires Ghidra running on :8089 with a program open):
  ```bash
  cmd.exe /c 'cd /d C:\Ghidra\ghidra-mcp && python -m pytest tests/integration/test_phase3_datatypes.py -k Bitfield --no-cov -q'
  ```

---

## Task 1: Add the `add_struct_bitfield` tool method

**Files:**
- Modify: `src/main/java/com/xebyte/core/DataTypeService.java` (insert a new method + constant immediately before the `remove_struct_field` doc comment, ~line 1582)
- Modify: `tests/endpoints.json` (append one endpoint entry, bump `total_endpoints`)

- [ ] **Step 1: Add the constant and method to `DataTypeService.java`**

Find this exact block (it is the doc comment + annotation that begins the
`remove_struct_field` tool):

```java
    /**
     * Remove a field from an existing structure
     */
    @McpTool(path = "/remove_struct_field", method = "POST", description = "Remove a field from a structure", category = "datatype")
```

Insert the following code **immediately before** that block (so the new code
sits between the `addStructField` backward-compat overload and
`remove_struct_field`):

```java
    /** Valid-identifier check for bitfield member names (light validation, no prefix policy). */
    private static final Pattern BITFIELD_NAME_PATTERN = Pattern.compile("^[A-Za-z_][A-Za-z0-9_]*$");

    /**
     * Add an explicitly-placed bitfield member to a non-packed structure.
     * Wraps Structure.insertBitFieldAt; the storage byte width is derived from
     * the base type, so the caller supplies only byte/bit offsets and bit size.
     */
    @McpTool(path = "/add_struct_bitfield", method = "POST",
            description = "Add an explicitly-placed bitfield member to a non-packed structure. Caller gives the exact byte_offset, bit_offset, and bit_size; storage width is derived from base_type. Use for hardware-register and flag structs so the decompiler can recover bitfields by name.",
            category = "datatype")
    public Response addStructBitfield(
            @Param(value = "struct_name", source = ParamSource.BODY) String structName,
            @Param(value = "base_type", source = ParamSource.BODY) String baseTypeName,
            @Param(value = "byte_offset", source = ParamSource.BODY, defaultValue = "-1") int byteOffset,
            @Param(value = "bit_offset", source = ParamSource.BODY, defaultValue = "-1") int bitOffset,
            @Param(value = "bit_size", source = ParamSource.BODY, defaultValue = "-1") int bitSize,
            @Param(value = "name", source = ParamSource.BODY) String name,
            @Param(value = "comment", source = ParamSource.BODY, defaultValue = "") String comment,
            @Param(value = "program", description = "Target program name", defaultValue = "") String programName) {
        ServiceUtils.ProgramOrError pe = ServiceUtils.getProgramOrError(programProvider, programName);
        if (pe.hasError()) return pe.error();
        Program program = pe.program();

        if (structName == null || structName.isEmpty()) return Response.err("Structure name is required");
        if (baseTypeName == null || baseTypeName.isEmpty()) return Response.err("base_type is required");
        if (name == null || name.isEmpty()) return Response.err("Bitfield name is required");
        if (!BITFIELD_NAME_PATTERN.matcher(name).matches()) {
            return Response.err("Invalid bitfield name '" + name
                + "': must be a valid identifier ([A-Za-z_][A-Za-z0-9_]*)");
        }
        if (byteOffset < 0) return Response.err("byte_offset is required and must be >= 0");
        if (bitOffset < 0) return Response.err("bit_offset is required and must be >= 0");
        if (bitSize < 1) return Response.err("bit_size is required and must be >= 1");

        final String finalComment = (comment == null) ? "" : comment;
        AtomicReference<Response> responseRef = new AtomicReference<>();

        try {
            SwingUtilities.invokeAndWait(() -> {
                int tx = program.startTransaction("Add struct bitfield");
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
                    if (struct.isPackingEnabled()) {
                        responseRef.set(Response.err("Structure '" + structName
                            + "' has packing enabled; add_struct_bitfield supports non-packed structures only"));
                        return;
                    }

                    DataType baseType = ServiceUtils.resolveDataType(dtm, baseTypeName);
                    if (baseType == null) {
                        responseRef.set(Response.err("base_type not found: " + baseTypeName));
                        return;
                    }
                    DataType probe = baseType;
                    while (probe instanceof TypeDef) {
                        probe = ((TypeDef) probe).getBaseDataType();
                    }
                    if (!(probe instanceof AbstractIntegerDataType)) {
                        responseRef.set(Response.err("base_type '" + baseTypeName
                            + "' is not an integer type; bitfields require an integer base type"));
                        return;
                    }

                    int byteWidth = baseType.getLength();
                    int maxBits = byteWidth * 8;
                    if (bitSize > maxBits) {
                        responseRef.set(Response.err("bit_size " + bitSize + " exceeds base type width ("
                            + maxBits + " bits for " + baseTypeName + ")"));
                        return;
                    }
                    if (bitOffset + bitSize > maxBits) {
                        responseRef.set(Response.err("bit_offset " + bitOffset + " + bit_size " + bitSize
                            + " exceeds base type width (" + maxBits + " bits)"));
                        return;
                    }

                    DataTypeComponent comp = struct.insertBitFieldAt(
                        byteOffset, byteWidth, bitOffset, baseType, bitSize, name, finalComment);
                    committed = true;

                    int placedBitOffset = bitOffset;
                    if (comp.getDataType() instanceof BitFieldDataType bf) {
                        placedBitOffset = bf.getBitOffset();
                    }
                    Map<String, Object> data = new LinkedHashMap<>();
                    data.put("success", true);
                    data.put("struct", structName);
                    data.put("name", name);
                    data.put("byte_offset", comp.getOffset());
                    data.put("bit_offset", placedBitOffset);
                    data.put("bit_size", bitSize);
                    data.put("base_type", baseTypeName);
                    data.put("bitfield_type", comp.getDataType().getName());
                    data.put("struct_length", struct.getLength());
                    responseRef.set(Response.ok(data));
                } catch (Exception e) {
                    responseRef.set(Response.err("Error adding bitfield: " + e.getMessage()));
                } finally {
                    program.endTransaction(tx, committed);
                }
            });
        } catch (InterruptedException | InvocationTargetException e) {
            return Response.err("Failed to execute bitfield addition on Swing thread: " + e.getMessage());
        }

        Response r = responseRef.get();
        return r != null ? r : Response.err("Bitfield addition produced no response");
    }

```

(All referenced types — `Pattern`, `Map`, `LinkedHashMap`, `AtomicReference`,
`Structure`, `DataType`, `DataTypeManager`, `DataTypeComponent`,
`BitFieldDataType`, `AbstractIntegerDataType`, `TypeDef` — are already covered by
the existing `import java.util.*`, `java.util.regex.Pattern`,
`java.util.concurrent.atomic.AtomicReference`, and
`ghidra.program.model.data.*` imports. `ParamSource`, `Response`, `McpTool`,
`Param`, and `ServiceUtils` are in the same `com.xebyte.core` package. No new
imports are needed.)

- [ ] **Step 2: Verify it compiles**

Run the **Compile check** command from the Environment section.
Expected: `BUILD SUCCESSFUL`. (Deprecation warnings are pre-existing and fine.)
If it fails, fix the reported error before continuing.

- [ ] **Step 3: Register the endpoint in `tests/endpoints.json`**

The file is a JSON object with an `endpoints` array and a `total_endpoints`
integer. Append this object to the **end of the `endpoints` array**:

```json
    {
      "path": "/add_struct_bitfield",
      "method": "POST",
      "category": "datatype",
      "params": [
        "struct_name",
        "base_type",
        "byte_offset",
        "bit_offset",
        "bit_size",
        "name",
        "comment",
        "program"
      ],
      "description": "Add a bitfield member to a structure"
    }
```

Then increment the top-level `total_endpoints` value by exactly 1 (it is
currently `244` → set it to `245`). Do not change anything else.

- [ ] **Step 4: Verify endpoints.json parity**

Run the **Offline Java tests** command from the Environment section.
Expected: `BUILD SUCCESSFUL` — `EndpointsJsonParityTest` passes (it verifies
every `@McpTool` is listed and `total_endpoints` equals the array length).
If `EndpointsJsonParityTest` reports a description mismatch, set the
endpoints.json `description` to match what the test expects and re-run.

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/xebyte/core/DataTypeService.java tests/endpoints.json
git commit -m "$(cat <<'EOF'
feat(datatype): add_struct_bitfield tool for explicit bitfield placement

Wraps Structure.insertBitFieldAt; storage byte width is derived from
base_type. Non-packed structs only; light identifier validation, no
Hungarian prefix. Enables the Ghidra 12.1 decompiler to recover
bitfields by name.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add the `Bits` column to `get_struct_layout`

**Files:**
- Modify: `src/main/java/com/xebyte/core/DataTypeService.java` (the `getStructLayout` method, ~lines 292–303)

- [ ] **Step 1: Replace the layout header and component loop**

Find this exact block inside `getStructLayout`:

```java
        result.append("Layout:\n");
        result.append("Offset | Size | Type | Name\n");
        result.append("-------|------|------|-----\n");

        for (DataTypeComponent component : struct.getDefinedComponents()) {
            result.append(String.format("%6d | %4d | %-20s | %s\n",
                component.getOffset(),
                component.getLength(),
                component.getDataType().getName(),
                component.getFieldName() != null ? component.getFieldName() : "(unnamed)"));
        }
```

Replace it with:

```java
        result.append("Layout:\n");
        result.append("Offset | Size | Type | Name | Bits\n");
        result.append("-------|------|------|------|-----\n");

        for (DataTypeComponent component : struct.getDefinedComponents()) {
            String bits = "";
            if (component.isBitFieldComponent()
                    && component.getDataType() instanceof BitFieldDataType bf) {
                bits = bf.getBitOffset() + ":" + bf.getBitSize();
            }
            result.append(String.format("%6d | %4d | %-20s | %-20s | %s\n",
                component.getOffset(),
                component.getLength(),
                component.getDataType().getName(),
                component.getFieldName() != null ? component.getFieldName() : "(unnamed)",
                bits));
        }
```

This appends a 5th column (`Bits`) showing `bit_offset:bit_size` for bitfield
components and blank for regular fields. Columns 1–4 are unchanged, so existing
consumers that parse them still work.

- [ ] **Step 2: Verify it compiles**

Run the **Compile check** command from the Environment section.
Expected: `BUILD SUCCESSFUL`.

- [ ] **Step 3: Commit**

```bash
git add src/main/java/com/xebyte/core/DataTypeService.java
git commit -m "$(cat <<'EOF'
feat(datatype): show bitfield bit positions in get_struct_layout

Adds a Bits column reporting bit_offset:bit_size for bitfield
components so add_struct_bitfield placements can be verified without a
decompiler round-trip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Integration tests

**Files:**
- Modify: `tests/integration/test_phase3_datatypes.py` (add a `TestStructBitfield` class)

> Note: these tests require the new JAR deployed and Ghidra running with a
> program open. They are written here but only run in Task 4 after deploy.

- [ ] **Step 1: Add the `TestStructBitfield` class**

Append this class to the end of `tests/integration/test_phase3_datatypes.py`.
It reuses the module-level `is_error_response` helper and the `http_client`
fixture already used by `TestStructFieldOperations`:

```python
class TestStructBitfield:
    """Test add_struct_bitfield and bitfield read-back in get_struct_layout."""

    def _make_struct(self, http_client):
        """Create a struct with a 4-byte header field; bitfields go at offset 4+."""
        struct_name = f"BfStruct_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={
                "name": struct_name,
                "fields": [{"name": "header", "type": "uint", "offset": 0}],
            },
        )
        return struct_name

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_add_bitfield_basic(self, http_client):
        """A bitfield placed in undefined space succeeds and echoes its placement."""
        struct_name = self._make_struct(http_client)
        response = http_client.post(
            "/add_struct_bitfield",
            data={
                "struct_name": struct_name,
                "base_type": "uint",
                "byte_offset": 4,
                "bit_offset": 5,
                "bit_size": 3,
                "name": "MODE",
            },
        )
        assert response.status_code == 200
        body = json.loads(response.text)
        assert body.get("success") is True
        assert body["name"] == "MODE"
        assert body["bit_offset"] == 5
        assert body["bit_size"] == 3

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_bitfield_visible_in_layout(self, http_client):
        """get_struct_layout shows the Bits column with bit_offset:bit_size."""
        struct_name = self._make_struct(http_client)
        http_client.post(
            "/add_struct_bitfield",
            data={
                "struct_name": struct_name,
                "base_type": "uint",
                "byte_offset": 4,
                "bit_offset": 5,
                "bit_size": 3,
                "name": "MODE",
            },
        )
        response = http_client.get(
            "/get_struct_layout", params={"struct_name": struct_name}
        )
        assert response.status_code == 200
        text = response.text
        assert "Bits" in text
        assert "5:3" in text

    @pytest.mark.requires_program
    def test_add_bitfield_nonexistent_struct(self, http_client):
        """Adding to a missing struct returns an error."""
        response = http_client.post(
            "/add_struct_bitfield",
            data={
                "struct_name": f"NoSuch_{uuid.uuid4().hex[:8]}",
                "base_type": "uint",
                "byte_offset": 0,
                "bit_offset": 0,
                "bit_size": 1,
                "name": "flag",
            },
        )
        assert response.status_code == 200
        assert is_error_response(response.text)

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_add_bitfield_bit_size_too_large(self, http_client):
        """bit_size larger than the base type width is rejected."""
        struct_name = self._make_struct(http_client)
        response = http_client.post(
            "/add_struct_bitfield",
            data={
                "struct_name": struct_name,
                "base_type": "byte",
                "byte_offset": 4,
                "bit_offset": 0,
                "bit_size": 9,
                "name": "toobig",
            },
        )
        assert response.status_code == 200
        assert is_error_response(response.text)

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_add_bitfield_invalid_name(self, http_client):
        """A name that is not a valid identifier is rejected."""
        struct_name = self._make_struct(http_client)
        response = http_client.post(
            "/add_struct_bitfield",
            data={
                "struct_name": struct_name,
                "base_type": "uint",
                "byte_offset": 4,
                "bit_offset": 0,
                "bit_size": 2,
                "name": "1bad",
            },
        )
        assert response.status_code == 200
        assert is_error_response(response.text)

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_add_bitfield_overlap_rejected(self, http_client):
        """Placing a bitfield over an existing component is rejected."""
        struct_name = self._make_struct(http_client)
        # byte_offset 0 overlaps the 4-byte 'header' field.
        response = http_client.post(
            "/add_struct_bitfield",
            data={
                "struct_name": struct_name,
                "base_type": "uint",
                "byte_offset": 0,
                "bit_offset": 0,
                "bit_size": 1,
                "name": "clash",
            },
        )
        assert response.status_code == 200
        assert is_error_response(response.text)
```

- [ ] **Step 2: Commit**

```bash
git add tests/integration/test_phase3_datatypes.py
git commit -m "$(cat <<'EOF'
test(datatype): integration coverage for add_struct_bitfield

Round-trip placement + layout read-back, plus error paths: missing
struct, oversized bit_size, invalid name, region overlap.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Build, deploy, and run the integration tests

**Files:** none modified — this task builds and verifies.

- [ ] **Step 1: Confirm Ghidra is closed**

The Gradle `deploy` task patches `FrontEndTool.xml`, and Ghidra overwrites that
file on exit. Ask the user to close Ghidra (CodeBrowser + project window)
before continuing. Do not proceed until confirmed.

- [ ] **Step 2: Build and deploy**

Run the **Build + deploy** command from the Environment section.
Expected: `BUILD SUCCESSFUL` and a line `Deployed extension archive: ...`.

- [ ] **Step 3: Start Ghidra and open a big-endian program**

Ask the user to start Ghidra and open a **big-endian** program — e.g. the
`tms470_fulldump_main.bin` ARM:BE binary. The spec requires the bitfield
bit-offset round-trip to be exercised on a big-endian target rather than
assumed; the integration tests run against the currently-open program, so it
must be big-endian. Confirm the server is up:

```bash
curl -s -m 5 http://127.0.0.1:8089/check_connection
```
Expected: `Connected: GhidraMCP plugin running with program '...'`.

Confirm it is big-endian:

```bash
curl -s -m 5 http://127.0.0.1:8089/get_metadata | grep -i endian
```
Expected: `Endian: Big`.

- [ ] **Step 4: Confirm the tool registered**

```bash
curl -s -m 8 http://127.0.0.1:8089/mcp/schema | python3 -c "import sys,json; t=json.load(sys.stdin)['tools']; print('add_struct_bitfield' in [x['path'].lstrip('/') for x in t] or '/add_struct_bitfield' in [x['path'] for x in t])"
```
Expected: `True`.

- [ ] **Step 5: Run the bitfield integration tests**

Run the **Integration tests** command from the Environment section.
Expected: all `TestStructBitfield` tests PASS.

The `bit_offset == 5` / `"5:3"` assertions pin Ghidra's normalized bit-offset
round-trip on a big-endian target. If those two assertions fail but the value
reported in the response/layout is *consistent* (the tool echoes some other
normalized offset, e.g. because big-endian normalization differs), that is a
real finding, not a bug to patch over: read the actual `bit_offset` from the
JSON response, update the asserted constant in `test_add_bitfield_basic` and
`test_bitfield_visible_in_layout` to the observed value, note the observed
big-endian convention in a comment, and commit. The test still serves as the
regression pin — just pinned to the correct number. For any other failure,
debug using the systematic-debugging skill — do not patch over it.

- [ ] **Step 6: Run the full datatype integration file as a regression check**

```bash
cmd.exe /c 'cd /d C:\Ghidra\ghidra-mcp && python -m pytest tests/integration/test_phase3_datatypes.py --no-cov -q'
```
Expected: no new failures vs. the pre-change baseline (existing struct/enum
tests still pass; the `get_struct_layout` column change must not break
`TestStructFieldOperations`).

---

## Task 5: Documentation

**Files:**
- Modify: `docs/prompts/TOOL_USAGE_GUIDE.md`
- Modify: `docs/prompts/DATA_TYPE_INVESTIGATION_WORKFLOW.md`

- [ ] **Step 1: Document the tool in `TOOL_USAGE_GUIDE.md`**

Find the section that covers struct/datatype tools (search the file for
`add_struct_field`). Add an entry near it, matching the file's existing
formatting, with this content:

> **`add_struct_bitfield`** — Add an explicitly-placed bitfield member to a
> non-packed structure. Parameters: `struct_name`, `base_type` (integer type
> the bits are carved from, e.g. `uint`), `byte_offset`, `bit_offset`,
> `bit_size`, `name`, optional `comment`. Storage width is derived from
> `base_type`. Use for hardware-register and flag structs — once applied to
> data, the decompiler renders bitfield accesses by name. Verify placement
> with `get_struct_layout` (the `Bits` column reports `bit_offset:bit_size`).

- [ ] **Step 2: Document the tool in `DATA_TYPE_INVESTIGATION_WORKFLOW.md`**

Find where the workflow discusses defining struct fields (search for
`add_struct_field` or `create_struct`). Add a short paragraph, matching the
file's existing formatting:

> When a struct field is a packed set of flags or a hardware register,
> define the individual bits with `add_struct_bitfield` instead of leaving a
> raw integer. Give the exact `byte_offset`, `bit_offset`, and `bit_size` for
> each bit discovered from the datasheet or from shift/mask patterns in the
> decompiler. The struct must be non-packed. After placing bitfields, confirm
> them with `get_struct_layout` — the `Bits` column shows `bit_offset:bit_size`.

- [ ] **Step 3: Commit**

```bash
git add docs/prompts/TOOL_USAGE_GUIDE.md docs/prompts/DATA_TYPE_INVESTIGATION_WORKFLOW.md
git commit -m "$(cat <<'EOF'
docs: document add_struct_bitfield in tool + datatype guides

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Done

After Task 5, the feature is complete: a new `add_struct_bitfield` tool,
bitfield read-back in `get_struct_layout`, integration coverage, catalog
parity, and documentation. The MCP bridge picks up the tool automatically from
`/mcp/schema` — no bridge change.
