"""Type mapper — source column types to PostgreSQL type suggestions."""

import re

UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(r'^[^@]+@[^@]+\.[^@]+$')
JSON_PATTERN = re.compile(r'^\s*[\[{]')
IP_PATTERN = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')


def suggest_pg_type(
    source_type: str,
    column_name: str,
    nullable: bool = True,
    unique_count: int = 0,
    total_count: int = 0,
    sample_values: list[str] | None = None,
    df=None,
) -> dict:
    """Suggest a PostgreSQL type from source column metadata.

    Returns:
        {
            "type": "varchar(255)",
            "nullable": True,
            "identity": None,
            "default": None,
            "constraints": [],
            "confidence": "high" | "medium" | "low",
            "reason": "...",
        }
    """
    result = {
        "type": "text",
        "nullable": nullable,
        "identity": None,
        "default": None,
        "constraints": [],
        "confidence": "medium",
        "reason": "",
    }

    samples = sample_values or []
    if df is not None and not samples:
        samples = _extract_samples(df, column_name)

    name_lower = column_name.lower()

    if source_type == "INT":
        return _suggest_int(result, name_lower, nullable, unique_count, total_count, samples)

    if source_type == "FLOAT":
        return _suggest_float(result, samples)

    if source_type in ("VARCHAR", "TEXT"):
        return _suggest_string(result, source_type, unique_count, total_count, samples)

    direct_map = {
        "BOOLEAN": ("boolean", "boolean column"),
        "TIMESTAMP": ("timestamptz", "timestamp column — using timezone-aware type"),
        "UUID": ("uuid", "UUID column"),
        "BINARY": ("bytea", "binary data column"),
    }

    if source_type in direct_map:
        result["type"], result["reason"] = direct_map[source_type]
        result["confidence"] = "high"

    return result


def _extract_samples(df, column_name: str, max_samples: int = 50) -> list[str]:
    """Extract non-null sample values from a DataFrame column."""
    if column_name not in df.columns:
        return []
    series = df[column_name].dropna()
    return [str(v) for v in series.head(max_samples)]


def _suggest_int(
    result: dict,
    name_lower: str,
    nullable: bool,
    unique_count: int,
    total_count: int,
    samples: list[str],
) -> dict:
    result["type"] = "integer"
    result["reason"] = "integer column"

    if samples:
        try:
            int_vals = [int(v) for v in samples if v.strip()]
            if int_vals:
                max_val = max(int_vals)
                min_val = min(int_vals)
                if max_val > 2_147_483_647 or min_val < -2_147_483_648:
                    result["type"] = "bigint"
                    result["reason"] = f"max value {max_val} exceeds integer range"
                elif max_val < 32_768 and min_val > -32_768:
                    result["type"] = "smallint"
                    result["reason"] = f"max value {max_val} fits in smallint"
        except (ValueError, TypeError):
            pass

    is_pk_name = name_lower == "id" or name_lower.endswith("_id")
    is_all_unique = unique_count == total_count and total_count > 0
    if is_pk_name and is_all_unique and not nullable:
        result["type"] = "bigint"
        result["identity"] = "ALWAYS"
        result["confidence"] = "high"
        result["reason"] = "sequential unique non-null ID column"

    return result


def _suggest_float(result: dict, samples: list[str]) -> dict:
    result["type"] = "double precision"
    result["reason"] = "floating point column"

    if samples:
        all_2dp = all(
            re.match(r'^-?\d+\.\d{2}$', v.strip())
            for v in samples if v.strip()
        )
        if all_2dp and samples:
            result["type"] = "numeric(15,2)"
            result["confidence"] = "high"
            result["reason"] = "all values have 2 decimal places (currency pattern)"

    return result


def _suggest_string(
    result: dict,
    source_type: str,
    unique_count: int,
    total_count: int,
    samples: list[str],
) -> dict:
    if source_type == "TEXT":
        result["type"] = "text"
        result["reason"] = "long text column"
        return result

    if samples:
        non_empty = [v.strip() for v in samples if v.strip()]

        if non_empty and all(UUID_PATTERN.match(v) for v in non_empty):
            result["type"] = "uuid"
            result["confidence"] = "high"
            result["reason"] = "all values match UUID pattern"
            return result

        if non_empty and all(EMAIL_PATTERN.match(v) for v in non_empty):
            result["type"] = "varchar(320)"
            result["confidence"] = "high"
            result["reason"] = "all values match email pattern"
            return result

        if non_empty and all(JSON_PATTERN.match(v) for v in non_empty):
            result["type"] = "jsonb"
            result["confidence"] = "medium"
            result["reason"] = "values look like JSON objects/arrays"
            return result

        if non_empty and all(IP_PATTERN.match(v) for v in non_empty):
            result["type"] = "inet"
            result["confidence"] = "medium"
            result["reason"] = "values look like IP addresses"
            return result

        if non_empty:
            max_len = max(len(v) for v in non_empty)
            if max_len <= 50:
                result["type"] = "varchar(50)"
            elif max_len <= 255:
                result["type"] = "varchar(255)"
            else:
                result["type"] = "text"
            result["reason"] = f"max string length {max_len}"

    if unique_count <= 20 and total_count > 10:
        result["type"] = "enum"
        result["confidence"] = "medium"
        result["reason"] = f"only {unique_count} unique values — consider enum type"

    return result
