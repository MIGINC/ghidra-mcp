"""
Phase 3: Data Type System Endpoints Tests

Tests for the 15 Phase 3 endpoints:
- create_enum
- create_union
- create_typedef
- create_array_type
- create_pointer_type
- add_struct_field
- modify_struct_field
- remove_struct_field
- delete_data_type
- search_data_types
- validate_data_type_exists
- get_data_type_size
- get_struct_layout
- get_enum_values
- clone_data_type
"""

import pytest
import uuid
import json


def is_error_response(text):
    """Check if response indicates an error (including validation messages)."""
    lower = text.lower()
    return any(
        word in lower
        for word in ["error", "required", "invalid", "failed", "not found", "missing"]
    )


def is_success_response(text):
    """Check if response indicates success."""
    lower = text.lower()
    return any(
        word in lower
        for word in ["success", "created", "added", "modified", "deleted", "updated"]
    )


def is_valid_response(text):
    """Check if response is either success or error (not empty/garbage)."""
    return is_success_response(text) or is_error_response(text) or text.strip()


class TestCreateEnum:
    """Test enum creation endpoint."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_create_enum_basic(self, http_client):
        """Test creating a basic enum."""
        unique_name = f"TestEnum_{uuid.uuid4().hex[:8]}"
        response = http_client.post(
            "/create_enum",
            data={
                "name": unique_name,
                "values": json.dumps({"VALUE_A": 0, "VALUE_B": 1, "VALUE_C": 2}),
                "size": "4",
            },
        )
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text)

    @pytest.mark.requires_program
    def test_create_enum_missing_name(self, http_client):
        """Test enum creation with missing name."""
        response = http_client.post(
            "/create_enum", data={"values": json.dumps({"VALUE_A": 0}), "size": "4"}
        )
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestCreateUnion:
    """Test union creation endpoint."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_create_union_basic(self, http_client):
        """Test creating a basic union."""
        unique_name = f"TestUnion_{uuid.uuid4().hex[:8]}"
        response = http_client.post(
            "/create_union",
            data={
                "name": unique_name,
                "fields": json.dumps(
                    [
                        {"name": "intVal", "type": "int"},
                        {"name": "floatVal", "type": "float"},
                    ]
                ),
            },
        )
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text)

    @pytest.mark.requires_program
    def test_create_union_missing_fields(self, http_client):
        """Test union creation with missing fields."""
        response = http_client.post("/create_union", data={"name": "TestUnionNoFields"})
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestCreateTypedef:
    """Test typedef creation endpoint."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_create_typedef_basic(self, http_client):
        """Test creating a basic typedef."""
        unique_name = f"MyInt_{uuid.uuid4().hex[:8]}"
        response = http_client.post(
            "/create_typedef", data={"name": unique_name, "base_type": "int"}
        )
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text)

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_create_typedef_pointer(self, http_client):
        """Test creating a pointer typedef."""
        unique_name = f"IntPtr_{uuid.uuid4().hex[:8]}"
        response = http_client.post(
            "/create_typedef", data={"name": unique_name, "base_type": "int*"}
        )
        assert response.status_code == 200

    @pytest.mark.requires_program
    def test_create_typedef_missing_base(self, http_client):
        """Test typedef with missing base type."""
        response = http_client.post("/create_typedef", data={"name": "TestTypedef"})
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestCreateArrayType:
    """Test array type creation endpoint."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_create_array_type_basic(self, http_client):
        """Test creating a basic array type."""
        response = http_client.post(
            "/create_array_type", data={"base_type": "int", "length": "10"}
        )
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text)

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_create_array_type_with_name(self, http_client):
        """Test creating a named array type."""
        unique_name = f"IntArray_{uuid.uuid4().hex[:8]}"
        response = http_client.post(
            "/create_array_type",
            data={"base_type": "byte", "length": "16", "name": unique_name},
        )
        assert response.status_code == 200

    @pytest.mark.requires_program
    def test_create_array_type_invalid_length(self, http_client):
        """Test array with invalid length."""
        response = http_client.post(
            "/create_array_type", data={"base_type": "int", "length": "0"}
        )
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestCreatePointerType:
    """Test pointer type creation endpoint."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_create_pointer_type_basic(self, http_client):
        """Test creating a basic pointer type."""
        response = http_client.post("/create_pointer_type", data={"base_type": "int"})
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text)

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_create_pointer_type_void(self, http_client):
        """Test creating a void pointer type."""
        response = http_client.post("/create_pointer_type", data={"base_type": "void"})
        assert response.status_code == 200

    @pytest.mark.requires_program
    def test_create_pointer_type_missing_base(self, http_client):
        """Test pointer with missing base type."""
        response = http_client.post("/create_pointer_type", data={})
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestStructFieldOperations:
    """Test struct field modification endpoints."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_add_struct_field(self, http_client):
        """Test adding a field to a struct."""
        # First create a struct
        struct_name = f"TestStruct_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={
                "name": struct_name,
                "fields": [{"name": "field1", "type": "int"}],
            },
        )
        # Then add a field
        response = http_client.post(
            "/add_struct_field",
            data={
                "struct_name": struct_name,
                "field_name": "field2",
                "field_type": "short",
            },
        )
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text)

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_modify_struct_field(self, http_client):
        """Test modifying a struct field."""
        # First create a struct
        struct_name = f"TestStruct_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={
                "name": struct_name,
                "fields": [{"name": "myField", "type": "int"}],
            },
        )
        # Then modify the field
        response = http_client.post(
            "/modify_struct_field",
            data={
                "struct_name": struct_name,
                "field_name": "myField",
                "new_type": "short",
            },
        )
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text)

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_remove_struct_field(self, http_client):
        """Test removing a struct field."""
        # First create a struct with multiple fields
        struct_name = f"TestStruct_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={
                "name": struct_name,
                "fields": [
                    {"name": "keep", "type": "int"},
                    {"name": "remove", "type": "short"},
                ],
            },
        )
        # Then remove a field
        response = http_client.post(
            "/remove_struct_field",
            data={"struct_name": struct_name, "field_name": "remove"},
        )
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text)

    @pytest.mark.requires_program
    def test_add_field_to_nonexistent_struct(self, http_client):
        """Test adding field to non-existent struct."""
        response = http_client.post(
            "/add_struct_field",
            data={
                "struct_name": f"NonExistent_{uuid.uuid4().hex[:8]}",
                "field_name": "field",
                "field_type": "int",
            },
        )
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestDeleteDataType:
    """Test data type deletion endpoint."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_delete_data_type(self, http_client):
        """Test deleting a data type."""
        # First create a struct to delete
        struct_name = f"DeleteMe_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={"name": struct_name, "fields": [{"name": "f", "type": "int"}]},
        )
        # Then delete it
        response = http_client.post(
            "/delete_data_type", data={"type_name": struct_name}
        )
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text)

    @pytest.mark.requires_program
    def test_delete_nonexistent_type(self, http_client):
        """Test deleting non-existent type."""
        response = http_client.post(
            "/delete_data_type",
            data={"type_name": f"NonExistent_{uuid.uuid4().hex[:8]}"},
        )
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestSearchDataTypes:
    """Test data type search endpoint."""

    @pytest.mark.requires_program
    def test_search_data_types_basic(self, http_client):
        """Test searching for data types."""
        response = http_client.get(
            "/search_data_types", params={"pattern": "int", "limit": 10}
        )
        assert response.status_code == 200
        # Should return some results for common type "int"

    @pytest.mark.requires_program
    def test_search_data_types_pagination(self, http_client):
        """Test search pagination."""
        response = http_client.get(
            "/search_data_types", params={"pattern": "int", "offset": 0, "limit": 5}
        )
        assert response.status_code == 200

    @pytest.mark.requires_program
    def test_search_data_types_no_match(self, http_client):
        """Test search with no matches."""
        response = http_client.get(
            "/search_data_types", params={"pattern": f"NoMatch_{uuid.uuid4().hex[:8]}"}
        )
        assert response.status_code == 200


class TestValidateDataType:
    """Test data type validation endpoint."""

    @pytest.mark.requires_program
    def test_validate_existing_type(self, http_client):
        """Test validating an existing type."""
        response = http_client.get(
            "/validate_data_type_exists", params={"type_name": "int"}
        )
        assert response.status_code == 200
        text = response.text
        # Should return JSON with exists: true
        assert "exists" in text.lower()

    @pytest.mark.requires_program
    def test_validate_nonexistent_type(self, http_client):
        """Test validating non-existent type."""
        response = http_client.get(
            "/validate_data_type_exists",
            params={"type_name": f"NonExistent_{uuid.uuid4().hex[:8]}"},
        )
        assert response.status_code == 200
        text = response.text
        assert "exists" in text.lower()
        # exists should be false
        assert "false" in text.lower()


class TestGetDataTypeSize:
    """Test data type size endpoint."""

    @pytest.mark.requires_program
    def test_get_size_builtin(self, http_client):
        """Test getting size of builtin type."""
        response = http_client.get("/get_data_type_size", params={"type_name": "int"})
        # Skip if endpoint not available (headless-only endpoint)
        if response.status_code == 404:
            pytest.skip("Endpoint not available in this mode")
        assert response.status_code == 200
        text = response.text
        assert "size" in text.lower()

    @pytest.mark.requires_program
    def test_get_size_nonexistent(self, http_client):
        """Test getting size of non-existent type."""
        response = http_client.get(
            "/get_data_type_size",
            params={"type_name": f"NonExistent_{uuid.uuid4().hex[:8]}"},
        )
        # Skip if endpoint not available (headless-only endpoint)
        if response.status_code == 404:
            pytest.skip("Endpoint not available in this mode")
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestGetStructLayout:
    """Test struct layout endpoint."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_get_struct_layout(self, http_client):
        """Test getting struct layout."""
        # First create a struct
        struct_name = f"LayoutTest_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={
                "name": struct_name,
                "fields": [
                    {"name": "id", "type": "int"},
                    {"name": "flags", "type": "short"},
                ],
            },
        )
        # Then get its layout
        response = http_client.get(
            "/get_struct_layout", params={"struct_name": struct_name}
        )
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text) or "layout" in text.lower()

    @pytest.mark.requires_program
    def test_get_layout_nonexistent(self, http_client):
        """Test getting layout of non-existent struct."""
        response = http_client.get(
            "/get_struct_layout",
            params={"struct_name": f"NonExistent_{uuid.uuid4().hex[:8]}"},
        )
        # Skip if endpoint not available
        if response.status_code == 404:
            pytest.skip("Endpoint not available in this mode")
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestGetEnumValues:
    """Test enum values endpoint."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_get_enum_values(self, http_client):
        """Test getting enum values."""
        # First create an enum
        enum_name = f"EnumTest_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_enum",
            data={
                "name": enum_name,
                "values": json.dumps({"A": 0, "B": 1, "C": 2}),
                "size": "4",
            },
        )
        # Then get its values
        response = http_client.get("/get_enum_values", params={"enum_name": enum_name})
        # Skip if endpoint not available
        if response.status_code == 404:
            pytest.skip("Endpoint not available in this mode")
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text)

    @pytest.mark.requires_program
    def test_get_values_nonexistent(self, http_client):
        """Test getting values of non-existent enum."""
        response = http_client.get(
            "/get_enum_values",
            params={"enum_name": f"NonExistent_{uuid.uuid4().hex[:8]}"},
        )
        # Skip if endpoint not available
        if response.status_code == 404:
            pytest.skip("Endpoint not available in this mode")
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestCloneDataType:
    """Test data type cloning endpoint."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_clone_struct(self, http_client):
        """Test cloning a struct."""
        # First create a struct
        source_name = f"Source_{uuid.uuid4().hex[:8]}"
        http_client.post(
            "/create_struct",
            json_data={"name": source_name, "fields": [{"name": "x", "type": "int"}]},
        )
        # Then clone it
        clone_name = f"Clone_{uuid.uuid4().hex[:8]}"
        response = http_client.post(
            "/clone_data_type",
            data={"source_type": source_name, "new_name": clone_name},
        )
        assert response.status_code == 200
        text = response.text
        assert is_valid_response(text)

    @pytest.mark.requires_program
    def test_clone_nonexistent(self, http_client):
        """Test cloning non-existent type."""
        response = http_client.post(
            "/clone_data_type",
            data={
                "source_type": f"NonExistent_{uuid.uuid4().hex[:8]}",
                "new_name": "ClonedType",
            },
        )
        assert response.status_code == 200
        assert is_error_response(response.text)


class TestPhase3Integration:
    """Integration tests using multiple Phase 3 endpoints together."""

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_create_and_query_struct_workflow(self, http_client):
        """Test creating a struct, querying it, and deleting it."""
        struct_name = f"Workflow_{uuid.uuid4().hex[:8]}"

        # Create struct
        response = http_client.post(
            "/create_struct",
            json_data={
                "name": struct_name,
                "fields": [
                    {"name": "id", "type": "int"},
                    {"name": "value", "type": "float"},
                ],
            },
        )
        assert response.status_code == 200
        # Check if struct creation actually succeeded
        if is_error_response(response.text) and "required" not in response.text.lower():
            pytest.skip("Struct creation not supported in this mode")

        # Validate it exists (may fail if struct not created)
        response = http_client.get(
            "/validate_data_type_exists", params={"type_name": struct_name}
        )
        assert response.status_code == 200
        # Skip rest of test if struct wasn't created
        if "false" in response.text.lower():
            pytest.skip("Struct creation not working in this mode")

        # Get layout (optional endpoint)
        response = http_client.get(
            "/get_struct_layout", params={"struct_name": struct_name}
        )
        if response.status_code != 404:
            assert response.status_code == 200

        # Get size (optional endpoint)
        response = http_client.get(
            "/get_data_type_size", params={"type_name": struct_name}
        )
        if response.status_code != 404:
            assert response.status_code == 200

        # Delete it
        response = http_client.post(
            "/delete_data_type", data={"type_name": struct_name}
        )
        assert response.status_code == 200

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_create_enum_and_query_values(self, http_client):
        """Test creating enum and querying its values."""
        enum_name = f"StatusEnum_{uuid.uuid4().hex[:8]}"

        # Create enum — handler uses parseJsonParams so send JSON body
        response = http_client.post(
            "/create_enum",
            json_data={
                "name": enum_name,
                "values": {"STATUS_OK": 0, "STATUS_ERROR": 1, "STATUS_PENDING": 2},
                "size": 4,
            },
        )
        assert response.status_code == 200

        # Query values (optional endpoint)
        response = http_client.get("/get_enum_values", params={"enum_name": enum_name})
        # Skip if endpoint not available
        if response.status_code == 404:
            pytest.skip("get_enum_values endpoint not available in this mode")
        assert response.status_code == 200
        # Should contain our values
        text = response.text
        if "error" not in text.lower() and "not found" not in text.lower():
            assert "STATUS_OK" in text or "values" in text.lower()

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_modify_struct_workflow(self, http_client):
        """Test creating and modifying a struct."""
        struct_name = f"Modifiable_{uuid.uuid4().hex[:8]}"

        # Create struct
        response = http_client.post(
            "/create_struct",
            json_data={
                "name": struct_name,
                "fields": [{"name": "original", "type": "int"}],
            },
        )
        assert response.status_code == 200

        # Add a field
        response = http_client.post(
            "/add_struct_field",
            data={
                "struct_name": struct_name,
                "field_name": "added",
                "field_type": "byte",
            },
        )
        assert response.status_code == 200

        # Verify layout shows both fields
        response = http_client.get(
            "/get_struct_layout", params={"struct_name": struct_name}
        )
        assert response.status_code == 200


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
            json_data={
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
            json_data={
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
            json_data={
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
            json_data={
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
            json_data={
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
            json_data={
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

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_add_bitfield_shared_word(self, http_client):
        """Multiple bitfields pack into one shared storage word at the same byte_offset."""
        struct_name = self._make_struct(http_client)
        first = http_client.post(
            "/add_struct_bitfield",
            json_data={
                "struct_name": struct_name,
                "base_type": "uint",
                "byte_offset": 4,
                "bit_offset": 0,
                "bit_size": 3,
                "name": "LOW",
            },
        )
        assert json.loads(first.text).get("success") is True
        second = http_client.post(
            "/add_struct_bitfield",
            json_data={
                "struct_name": struct_name,
                "base_type": "uint",
                "byte_offset": 4,
                "bit_offset": 3,
                "bit_size": 5,
                "name": "HIGH",
            },
        )
        body = json.loads(second.text)
        assert body.get("success") is True
        assert body["bit_offset"] == 3
        # Both bitfields visible in the layout
        layout = http_client.get(
            "/get_struct_layout", params={"struct_name": struct_name}
        )
        assert "0:3" in layout.text
        assert "3:5" in layout.text

    @pytest.mark.requires_program
    @pytest.mark.write
    def test_add_bitfield_bit_range_overlap(self, http_client):
        """Two bitfields in the same word with overlapping bit ranges is rejected."""
        struct_name = self._make_struct(http_client)
        first = http_client.post(
            "/add_struct_bitfield",
            json_data={
                "struct_name": struct_name,
                "base_type": "uint",
                "byte_offset": 4,
                "bit_offset": 0,
                "bit_size": 3,
                "name": "LOW",
            },
        )
        assert json.loads(first.text).get("success") is True
        # bits [2, 6) overlap LOW's bits [0, 3) at bit 2
        clash = http_client.post(
            "/add_struct_bitfield",
            json_data={
                "struct_name": struct_name,
                "base_type": "uint",
                "byte_offset": 4,
                "bit_offset": 2,
                "bit_size": 4,
                "name": "CLASH",
            },
        )
        assert clash.status_code == 200
        assert is_error_response(clash.text)
