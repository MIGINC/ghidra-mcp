# Bitfield MCP Tooling — Design

**Date:** 2026-05-15
**Status:** Approved (design phase)
**Author:** brainstorming session

## Background

Ghidra 12.1's decompiler recovers and displays the names of bitfield
components in structured data types. When a struct containing bitfield
members is applied to data, the decompiler renders individual bitfield
accesses by name using standard field-access notation (`reg.EN`) instead of
the low-level shift/mask expressions, for both reads and writes — and can
break apart optimized expressions that touch several bitfields at once.

GhidraMCP cannot currently exploit this. `create_struct`,
`add_struct_field`, and `modify_struct_field` accept only `name` / `type` /
`offset` — there is no way to define a bitfield struct member, so the
decompiler has no named bitfields to recover. `get_struct_layout` prints a
text table that does not surface bit positioning.

This design adds the **create** half: a dedicated tool to define bitfield
struct members, plus the minimum read-back needed to verify placement.

## Goals

- Define bitfield struct members from MCP so the 12.1 decompiler can recover
  them by name.
- Verify placement without a decompiler round-trip.

## Non-goals

- Modifying or removing existing bitfield members (future work if needed).
- Inspecting/extracting bitfields the decompiler already recovered from
  decompiler output.
- Sequential/packed bitfield declaration (`addBitField`). Explicit placement
  only.
- Converting `get_struct_layout` to structured JSON output.

## Decisions (from brainstorming)

| Question | Decision |
| --- | --- |
| Scope | Create/write side only — define bitfield struct members. |
| Placement model | Explicit placement only — caller gives exact byte/bit offsets. |
| API shape | One dedicated new tool. `create_struct` is not changed. |
| Naming | Light validation only — valid-identifier check, no Hungarian prefix enforcement. |
| Layout read-back | Extend `get_struct_layout` to surface bit positioning (Approach B). |

## Design

### Component 1 — `add_struct_bitfield` tool

A new `@McpTool` method on `DataTypeService.java`.

```
POST /add_struct_bitfield
```

| Param | Type | Required | Notes |
| --- | --- | --- | --- |
| `struct_name` | string | yes | Target structure. Must exist and be a non-packed `Structure`. |
| `base_type` | string | yes | Integer storage type the bits are carved from (`uint`, `byte`, `ushort`, …). Must resolve to an integer-type data type. |
| `byte_offset` | int | yes | Byte offset within the struct where the bitfield storage region begins. |
| `bit_offset` | int | yes | Bit offset within the storage region, using Ghidra's normalized convention (round-trips with `get_struct_layout`). |
| `bit_size` | int | yes | Number of bits. Must satisfy `1 <= bit_size <= base_type bit width`. |
| `name` | string | yes | Bitfield member name. Light validation: must be a valid identifier. No Hungarian prefix applied or enforced. |
| `comment` | string | no | Member comment. Default empty. |
| `program` | string | no | Target program name. Active program if omitted. |

**Behavior**

1. Resolve the program; resolve `struct_name` to a `Structure`.
2. Reject if the struct has packing enabled (`isPackingEnabled()`) —
   `insertBitFieldAt` is for non-packed structures only.
3. Resolve `base_type` to a data type; reject if unresolvable or not an
   integer type.
4. Validate `bit_size` against the base type's bit width.
5. Validate `name` is a valid identifier.
6. In a transaction, call
   `Structure.insertBitFieldAt(byteOffset, byteWidth, bitOffset, baseType, bitSize, name, comment)`.
   `byteWidth` is **derived** from `base_type.getLength()` — not exposed as a
   parameter — keeping the API minimal.
7. Catch Ghidra exceptions (bit-region overlap, out-of-range placement) and
   return them as a structured conflict error.

**Response (success)** — JSON containing: success flag, struct name, the
placed component (`byte_offset`, `bit_offset`, `bit_size`, `name`), the
resolved bitfield type name (e.g. `uint:3`), and the struct's new length.

**Endianness.** The reference working binary is ARM:BE:32 (big-endian).
Ghidra's `bit_offset` is normalized so it round-trips consistently with what
`get_struct_layout` reports regardless of endianness. This is pinned by an
explicit big-endian regression test rather than assumed.

### Component 2 — `get_struct_layout` bit-position read-back

`get_struct_layout` already iterates `struct.getDefinedComponents()` and
prints a fixed text table with columns `Offset | Size | Type | Name`.

Add a fifth column, `Bits`. For components where
`component.isBitFieldComponent()` is true, populate it with
`bit_offset:bit_size` (e.g. `5:3`); leave it blank for regular fields. A
bitfield row then reads, for example:

```
Offset | Size | Type   | Name | Bits
     4 |    4 | uint:3 | MODE | 5:3
```

Appending a column preserves columns 1–4 for existing consumers that parse
the table. No JSON conversion (rejected Approach C — the text format is
consumed by existing prompts/tests).

### Error handling

All error conditions return a structured response; no exception leaks.

| Condition | Response |
| --- | --- |
| Struct not found / not a `Structure` | Clear "not found" / "not a structure" message. |
| Struct has packing enabled | Rejected — message states `insertBitFieldAt` is non-packed only. |
| `base_type` unresolvable or not an integer type | Rejected, naming the offending type. |
| `bit_size` < 1 or > base-type bit width | Rejected, stating the valid range. |
| `name` not a valid identifier | Rejected. |
| Bit region overlaps an existing component | Ghidra exception caught → structured conflict error. |

## Testing

- **Catalog parity.** New `@McpTool` makes `EndpointsJsonParityTest` fail
  until `tests/endpoints.json` is regenerated
  (`mvn test -Dtest=RegenerateEndpointsJson -Dregenerate=true`).
- **Offline Java + Integration Java**, per the CLAUDE.md `*Service.java`
  testing row.
- **Integration test:** create a non-packed struct, add several bitfields —
  including against a big-endian program — read back via
  `get_struct_layout`, and assert byte/bit offsets round-trip. Cover error
  paths: packed struct, bit-region overlap, out-of-range `bit_size`,
  invalid name.
- **Bridge.** The tool auto-registers from `/mcp/schema`; no bridge code
  change. `tests/unit/test_endpoint_catalog.py` covers catalog consistency.

## Files touched

| File | Change |
| --- | --- |
| `src/main/java/com/xebyte/core/DataTypeService.java` | New `add_struct_bitfield` method; `get_struct_layout` gains the `Bits` column. |
| `tests/endpoints.json` | New endpoint entry (regenerated). |
| `tests/integration/` datatype test | New round-trip + error-path coverage. |
| `docs/prompts/TOOL_USAGE_GUIDE.md` | Short entry for the new tool. |
| `docs/prompts/DATA_TYPE_INVESTIGATION_WORKFLOW.md` | Short entry for the new tool. |
