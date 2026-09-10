"""Bounded, versioned output-schema subset with an explicit preflight receipt (INV-OUTPUT-001).

Not a complete Structured Outputs validator. A schema is accepted only when every keyword it
uses is in the supported subset, so a misspelled keyword is a configuration-owner error at
preflight instead of a check that silently never runs. The receipt names the dialect, the
keywords seen and every check that ran; "ok" therefore always says what was checked.
"""
import hashlib
import json

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from codex_harness.domain.model import ContractError, require

CAUSE = "codex-output-schema-version-missing-type"
SCOPE = "codex-harness/research-audit/output-schema"
DIALECT = "https://json-schema.org/draft/2020-12/schema"
SUBSET_VERSION = 1
MAX_DEPTH = 32
MAX_BYTES = 256 * 1024
# Keywords Zeus sends and validates. Anything else is refused at preflight, never ignored.
SUPPORTED_KEYWORDS = frozenset({
    "$schema", "$id", "$ref", "$defs", "definitions", "$comment", "title", "description", "default", "examples",
    "deprecated", "readOnly", "writeOnly",
    "type", "enum", "const", "properties", "patternProperties", "additionalProperties", "unevaluatedProperties",
    "required", "dependentRequired", "dependentSchemas", "propertyNames", "minProperties", "maxProperties",
    "items", "prefixItems", "contains", "minContains", "maxContains", "unevaluatedItems", "minItems", "maxItems",
    "uniqueItems", "anyOf", "oneOf", "allOf", "not", "if", "then", "else",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "format",
})
ANNOTATIONS = frozenset({"$schema", "$id", "$comment", "title", "description", "default", "examples", "deprecated",
                         "readOnly", "writeOnly"})
CHECKS = ("json_encodable", "object_root", "draft2020_metaschema", "supported_keywords", "typed_constants",
          "required_declared", "depth_bound", "size_bound")


def _refuse(cause, path, message, schema_hash):
    raise ContractError(f"{cause}: {SCOPE} at {path}: {message}; {schema_hash}")


def preflight(schema):
    """Refuse anything outside the subset before a transport sees it; return the preflight receipt."""
    try:
        encoded = json.dumps(schema, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractError("Malformed outputSchema at $: expected JSON") from exc
    schema_hash = "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()
    require(isinstance(schema, dict), f"outputSchema at $ must be an object; {schema_hash}")
    require(len(encoded.encode()) <= MAX_BYTES, f"outputSchema at $ exceeds {MAX_BYTES} bytes; {schema_hash}")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        path = "$" + "".join(f"[{json.dumps(p)}]" for p in exc.path)
        raise ContractError(f"Malformed outputSchema at {path}: {exc.message}; {schema_hash}") from exc

    visited = set()
    keywords = set()
    deepest = [0]

    def walk(node, path, version=False, depth=1):
        if not isinstance(node, dict):
            return
        marker = (id(node), version)
        if marker in visited:
            return
        visited.add(marker)
        deepest[0] = max(deepest[0], depth)
        if depth > MAX_DEPTH:
            _refuse("codex-output-schema-too-deep", path, f"nesting exceeds {MAX_DEPTH}", schema_hash)
        unsupported = sorted(key for key in node if key not in SUPPORTED_KEYWORDS)
        if unsupported:
            # A keyword nobody validates is a check that never runs: refuse it as a configuration error.
            _refuse("codex-output-schema-unsupported-keyword", path,
                    "unsupported keyword(s) " + ", ".join(unsupported), schema_hash)
        keywords.update(node)
        # INV-RECURRENCE-001: preserve the confirmed cause; never infer it from prompt text.
        if "const" in node and "type" not in node:
            cause = CAUSE if version else "codex-output-schema-constant-missing-type"
            raise ContractError(f"{cause}: {SCOPE} at {path}: const requires explicit type; {schema_hash}")
        if "enum" in node and "type" not in node:
            _refuse("codex-output-schema-enum-missing-type", path,
                    "enum requires explicit type (1 and true, 1 and 1.0 are distinct only with a type)", schema_hash)
        if node.get("additionalProperties") is False and isinstance(node.get("required"), list):
            declared = set(node.get("properties", {})) if isinstance(node.get("properties"), dict) else set()
            missing = sorted(name for name in node["required"] if isinstance(name, str) and name not in declared)
            if missing and not isinstance(node.get("patternProperties"), dict):
                _refuse("codex-output-schema-required-undeclared", path,
                        "required names not declared under a closed object: " + ", ".join(missing), schema_hash)
        ref = node.get("$ref", "")
        if version and ref.startswith("#/"):
            target = schema
            try:
                for part in ref[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError):
                raise ContractError(f"Unresolved outputSchema reference at {path}: {ref}") from None
            walk(target, path + f"->$ref({ref})", True, depth + 1)
        for key in sorted(node):
            value = node[key]
            child_path = path + f"[{json.dumps(key)}]"
            if key in ANNOTATIONS:
                continue
            if key in {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}:
                for name in sorted(value):
                    walk(value[name], child_path + f"[{json.dumps(name)}]",
                         key == "properties" and name == "version", depth + 1)
            elif key in {"anyOf", "allOf", "oneOf", "prefixItems"}:
                for index, child in enumerate(value):
                    walk(child, child_path + f"[{index}]", version, depth + 1)
            elif key in {"items", "contains", "additionalProperties", "unevaluatedProperties",
                         "unevaluatedItems", "propertyNames", "not", "if", "then", "else"}:
                walk(value, child_path, version, depth + 1)

    walk(schema, "$")
    return {"schema_hash": schema_hash, "dialect": DIALECT, "subset_version": SUBSET_VERSION,
            "keywords": sorted(keywords), "checks": list(CHECKS), "max_depth": deepest[0],
            "bytes": len(encoded.encode())}
