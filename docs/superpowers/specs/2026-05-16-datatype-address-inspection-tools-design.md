# Datatype & Address Inspection Tools — Design

**Date:** 2026-05-16
**Status:** Approved, pending implementation plan

## Motivation

Operator feedback from a live RE session surfaced four gaps in the MCP tool
surface. Building a struct with bitfields currently takes `create_struct` plus
N× `add_struct_bitfield`, and because `add_struct_bitfield` rejects overlaps,
any bitfield region forces a delete-and-rebuild dance. Inspecting "what is at
this address?" required reconstructing metadata from raw `read_memory` bytes
plus decompiler inference. `list_globals` substring search returned empty for
symbols that demonstrably exist. And the standing memory TODO — a
non-compacting way to reserve bitfield space — is still open.

## Scope

Four work items, all Java-side service additions/fixes. No bridge changes
(new `@McpTool` methods are auto-registered by `AnnotationScanner`). C-header
import and a dedicated symbol-search tool were explicitly deferred.

| # | Item | Type | Service |
|---|------|------|---------|
| 1 | `define_struct` — atomic struct builder | New tool | `DataTypeService` |
| 2 | `describe_address` — address inspection | New tool | `ListingService` |
| 3 | `clear_struct_field` — non-compacting clear | New tool | `DataTypeService` |
| 4 | `list_globals` substring search fix | Bug fix | `ListingService` |

## 1. `define_struct` — atomic struct builder

**Path:** `POST /define_struct` · **Category:** `datatype`

Builds a complete structure from a single JSON layout array in one call. The
whole layout is declared at once, so there is no compaction and no
delete-rebuild cycle for bitfield regions.

### Parameters

- `name` (BODY) — new structure type name. Rejected if a type with this name
  already exists.
- `layout` (BODY, `fieldsJson = true`) — JSON array of layout entries.
- `packed` (BODY, default `false`) — enable structure packing.
- `program` (QUERY, default active program).

### Layout entry kinds

Each entry's kind is **inferred** from the keys present, with an optional
explicit `"kind"` override (`field` / `bitfield` / `gap`):

- **field** (default) — `{"name", "type", "offset"?}`. `type` is any
  resolvable Ghidra data type or existing struct name (nested structs are
  just a field whose `type` is a struct name). `offset` is a decimal byte
  offset; omit to append.
- **bitfield** — inferred when `bit_size` is present —
  `{"name", "base_type", "byte_offset", "bit_offset", "bit_size"}`. Same
  semantics and validation as `add_struct_bitfield`.
- **gap** — inferred when `size` is present and `name` is absent —
  `{"offset", "size"}`. Explicit undefined-byte padding. Holes left between
  explicitly-offset fields also remain undefined bytes automatically, so an
  explicit gap entry is only needed for trailing/standalone padding.

### Behaviour

1. Validate `name` is non-empty and unused; validate `layout` is a non-empty
   JSON array (reuse `badFieldsFormatHint` shape check from `create_struct`).
2. Parse all entries; classify each by kind. Reject malformed entries with a
   concrete "expected vs got" message naming the entry index.
3. Resolve every field/base type **before** the transaction. Unknown type →
   fail loud, no transaction opened.
4. Validate bitfield placement off-transaction with the same checks
   `add_struct_bitfield` uses (base type is integer, `bit_offset + bit_size`
   within base width, byte region does not overlap a non-bitfield field).
5. Compute required struct size from the max field/bitfield/gap extent.
6. In one transaction on the Swing EDT: create a `StructureDataType` of the
   computed size, `replaceAtOffset` each field, `insertBitFieldAt` each
   bitfield, apply `packed` if requested, then `dtm.addDataType`.
7. After `insertBitFieldAt`, verify the struct did not grow beyond the
   expected length (same relocation guard as `add_struct_bitfield`); if it
   did, the placement conflicted — roll the transaction back and return an
   error naming the offending bitfield.
8. On success: `flushEvents`, return the final layout (offsets, names, types,
   bit positions) and total size.

## 2. `describe_address` — address inspection

**Path:** `GET /describe_address` · **Category:** `listing`

One call answers "what is actually at this address?" Returns basic metadata
only — no xref samples, no containing-function context.

### Parameters

- `address` (QUERY) — target address. Multi-address-space programs may prefix
  with the space name (`mem:1000`), consistent with `get_xrefs_to`.
- `program` (QUERY, default active program).

### Returns (JSON)

- `address` — normalized address string.
- `symbol` — primary symbol name at the address, or `null`. Dynamic symbols
  (e.g. `PTR_*`, `DAT_*`) are reported with their synthesized name.
- `data_type` — defined data type name, or `null` if no data is defined.
- `size` — length in bytes of the defined data, or `null`.
- `xref_count` — `getReferenceCountTo(address)`.
- `pointer_target` — present only when the defined type is a pointer:
  `{ "address", "symbol", "data_type" }` for the pointee. Resolved
  recursively through chained pointers (bounded guard, e.g. 8 hops) so a
  `Foo **` reports the eventual `Foo`.

If the address is invalid or unresolvable, return a structured error.

## 3. `clear_struct_field` — non-compacting field clear

**Path:** `POST /clear_struct_field` · **Category:** `datatype`

Closes the memory TODO: a non-compacting way to reserve bitfield space.
`remove_struct_field` compacts (later fields shift down). `clear_struct_field`
replaces a field with undefined bytes of the **same length** — later fields
keep their offsets — so the freed region can host bitfields placed afterward
with `add_struct_bitfield`.

### Parameters

- `struct_name` (BODY) — target structure.
- `field_name` (BODY) — field to clear, resolved by name to its ordinal.
- `program` (QUERY, default active program).

### Behaviour

In one transaction on the Swing EDT: resolve the struct, find the component
whose field name matches → its ordinal, call `Structure.clearComponent(ordinal)`,
return the cleared offset and length. Errors: struct not found, not a
structure, field name not found. `remove_struct_field` is left unchanged.

## 4. Fix `list_globals` substring search

### Root cause

`listGlobals` Pass 1 iterates `symbolTable.getSymbols(globalNamespace)`, which
**excludes dynamically-generated symbols**. Auto-created pointer labels such as
`PTR_CarConfigSource_00017888` are dynamic — not stored in the symbol table,
synthesized on demand from the pointer data and its target — so Pass 1 never
iterates them. Pass 2 (the raw-undefined-address walk) then also skips the
address, because line 610 `symbolTable.getPrimarySymbol(addr) != null`
returns the dynamic symbol and `continue`s. The address falls through both
passes and is never emitted — so any `name_substring` against it returns
empty.

### Fix

Change Pass 1 to iterate `symbolTable.getAllSymbols(true)` — the `true`
argument includes dynamic symbols — filtered to global scope with
`symbol.isGlobal()`. Every existing gate is preserved unchanged: the
`SymbolType.FUNCTION` skip, the code-address rejection, the data-section gate,
the named/undefined axis, the type-assignment axis, `min_xrefs`, and the
substring match. Dynamic `PTR_*` / `DAT_*` labels now get surfaced and are
substring-matchable. Pass 2 remains the fallback for addresses with no symbol
at all (dynamic or otherwise). The legacy 4-arg `listGlobals` overload is
unaffected.

## Testing

Per `CLAUDE.md` change→test mapping:

- **Offline Java** — `com.xebyte.offline.*`: `EndpointsJsonParityTest` must
  pass after the three new `@McpTool` methods are added. Regenerate
  `tests/endpoints.json` via `mvn test -Dtest=RegenerateEndpointsJson
  -Dregenerate=true` and commit it.
- **Integration (post-deploy)** — `tests/integration/test_readonly_endpoints.py`
  covers `describe_address` and `list_globals`;
  `tests/integration/test_safe_write_endpoints.py` covers `define_struct` and
  `clear_struct_field`. New test cases:
  - `define_struct` — plain fields, a bitfield region, a nested struct, a
    gap; round-trip via `get_struct_layout`; duplicate-name rejection;
    unknown-type rejection; bitfield-overlap rejection.
  - `describe_address` — defined-typed data, a pointer (verify
    `pointer_target`), an undefined address, an invalid address.
  - `clear_struct_field` — clear a field, verify via `get_struct_layout`
    that later fields kept their offsets and the region is undefined bytes;
    then `add_struct_bitfield` into the cleared region succeeds.
  - `list_globals` — `name_substring` matching a dynamic `PTR_*` label now
    returns it (regression for the root cause).
- **Java integration** — `EndpointRegistrationTest` confirms the new routes
  register.
- No bridge changes; `bridge_mcp_ghidra.py` line cap untouched.

## Out of scope

- C-header / typedef importer (`import_c_types`) — deferred to a follow-up.
- Dedicated full-symbol-table `search_symbols` tool — deferred; `list_globals`
  fix is the targeted answer for now.
- `describe_address` xref samples and containing-function context.
