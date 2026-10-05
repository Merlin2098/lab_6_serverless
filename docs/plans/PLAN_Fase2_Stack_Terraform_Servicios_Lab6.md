# Fase 2 — Stack Terraform y servicios del Lab 6: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Nota posterior:** este plan es histórico. El Makefile ya no tiene `deploy`, `fault-on/off` ni `tf-*` (Terraform se ejecuta directo) y Step Functions inicia el Crawler (`StartCrawler`). Ver [guia_deploy.md](../deploy/guia_deploy.md) para los comandos vigentes.

**Goal:** Dejar el lab de la Sesión 06 listo para desplegar con `make deploy`: Lambda validadora (imagen), datos de prueba, stack Terraform en 6 módulos, ajustes al Makefile, pruebas, ADR y guía del alumno.

**Architecture:** S3 `raw/*.csv` → EventBridge (wildcard) → Step Functions (Retry + Catch) → Lambda desde imagen ECR que valida y escribe en `processed/orders/`; Crawler + Data Catalog + Athena (workgroup propio) verifican el resultado fuera del workflow. Terraform en módulos por servicio bajo `infra/modules/`; la imagen se publica con un `make deploy` de 3 pasos visibles.

**Tech Stack:** Python 3.11+ (handler corre en el runtime de Lambda; boto3 ya incluido), pytest, Terraform ≥ 1.6 con provider AWS `~> 5.0`, Docker, GNU Make (Git Bash), AWS CLI v2.

**Spec:** [docs/specs/SPEC_Fase2_Stack_Terraform_Servicios_Lab6.md](../specs/SPEC_Fase2_Stack_Terraform_Servicios_Lab6.md) (revisión 2). Spec base: [docs/specs/SPEC_Laboratorio_Sesion_06_Serverless_Orquestacion_Contenedores.md](../specs/SPEC_Laboratorio_Sesion_06_Serverless_Orquestacion_Contenedores.md). Contrato del agente: [AGENTS.md](../../AGENTS.md).

## Global Constraints

- Región `us-east-1`; backend local; una sola región para ECR, Lambda y la regla de EventBridge.
- Terraform `>= 1.6.0`, provider `hashicorp/aws` `~> 5.0` (ya en `infra/providers.tf`, no tocar).
- **El agente NO ejecuta `terraform apply` ni `terraform destroy`** (AGENTS.md y `.claude/settings.json`). Solo `init -backend=false`, `fmt`, `validate`. Los pasos que requieren AWS (deploy, tests `cloud`, ensayo) los ejecuta el usuario (Task 11).
- Nunca borrar ni sobrescribir `terraform.tfstate`.
- Tags comunes con `CostCenter` en todos los recursos que admiten tags.
- Todo log group declarado lleva `retention_in_days` y nombre propio por stack. **No** declarar `/aws-glue/crawlers` (compartido; excepción documentada en el ADR).
- Sin `Action: "*"` en ninguna política. El único `Resource: "*"` permitido es la entrega de logs de Step Functions (módulo `orchestration`), con comentario que lo justifique.
- Sin S3 versioning; `enable_budget_guardrail` default `false`; ECR `IMMUTABLE` + `force_delete = true`; S3 y Athena con `force_destroy = true`.
- Valores que cambian por entorno viven en variables o env vars, nunca hardcodeados en el handler.
- Lambda: `package_type = "Image"`, `x86_64`, 256 MB, timeout 30 s. La imagen se construye con `--platform linux/amd64 --provenance=false`.
- Handler: `src/lambdas/validator/app.py` **sin imports relativos** (el Dockerfile copia solo ese archivo, plano, y `CMD ["app.handler"]`).
- Python: ejecutar con `python scripts/testing/run_pytest.py ...` / `make test` / `make lint`; dependencias solo vía `uv` (`pyproject.toml`). No añadir dependencias nuevas.
- El proyecto **no es un repo git**: los pasos "Checkpoint" no hacen commit. Si el usuario inicializa git, hacer un commit por Task con el mensaje indicado.
- Estilo: `from __future__ import annotations`, type hints, tests con funciones `test_*` (como `tests/test_example_job.py`). Nombres de archivos de test únicos en todo `tests/` (no hay `__init__.py` en `tests/`).
- Finales de línea LF (`.gitattributes`).

## Review Focus

Entradas que el spec implica pero que ningún flujo feliz ejercita; cada una tiene su test en la Task indicada.

1. **CSV guardado desde Excel con BOM UTF-8** → debe validarse como válido y la salida **no** debe llevar BOM (si no, el Crawler nombraría la primera columna `﻿order_id`). Test en Task 2.
2. **Clave con espacios o caracteres especiales** (`raw/orders 2026 10.csv`; EventBridge entrega la clave sin URL-encode) → se usa tal cual y la salida conserva el nombre base. Test en Task 2.
3. **Archivo con solo encabezado** → `no_data_rows`, sin excepción y sin salida. Test en Task 2.
4. **Fila con menos columnas que el encabezado o `amount` vacío** → `invalid_amount: row N`, sin excepción. Test en Task 2.
5. **`amount` con `NaN`, `Infinity` o `1_000`** (valores que `Decimal` acepta pero Athena no) → inválido. Test en Task 2.

---

## File Structure

| Archivo | Responsabilidad | Task |
|---|---|---|
| `docs/internal/adr/0001-pipeline-serverless-orientado-a-eventos.md` | Decisión de arquitectura (exigida por AGENTS.md) | 1 |
| `src/lambdas/__init__.py`, `src/lambdas/validator/__init__.py` | Paquetes (solo para tests locales) | 2 |
| `src/lambdas/validator/app.py` | Handler + `validate_csv` pura | 2 |
| `tests/lambdas/test_validator.py` | Unitarias de validación y handler (S3 falso) | 2 |
| `data/samples/*` | CSV/JSON de prueba (F1, F2, F3, inválidos, prueba.*) | 3 |
| `tests/lambdas/test_samples.py` | Los samples producen los resultados y totales esperados | 3 |
| `.gitattributes` | LF para `.csv`, `.tf`, `.tftpl` | 3 |
| `infra/main.tf`, `infra/budget.tf`, `infra/variables.tf`, `infra/outputs.tf`, `infra/terraform.tfvars.example` | Raíz: composición de módulos | 4 (y se amplía en 5–7) |
| `infra/modules/storage/*` | Bucket S3 + notificaciones EventBridge | 4 |
| `infra/modules/registry/*` | ECR | 4 |
| `infra/modules/compute/*` | Lambda + rol + log group + fallo inyectado | 5 |
| `infra/modules/orchestration/*` | State machine + rol + log group + plantilla ASL | 6 |
| `tests/infra/test_pipeline_asl.py` | La definición ASL es JSON válido y correcto | 6 |
| `infra/modules/events/*` | Regla EventBridge + rol | 7 |
| `infra/modules/catalog/*` | Glue DB + Crawler + Athena | 7 |
| `tests/infra/test_terraform_guardrails.py` | Reglas de AGENTS.md sobre el HCL | 8 |
| `Makefile` | Retira `package-zip`; añade `deploy`, `fault-on/off`, `smoke`, `executions` | 9 |
| `tests/aws/test_stack.py` | Tests `cloud` (estructura + extremo a extremo) | 10 |
| `docs/lab/guia_alumno.md` | Guía de exploración del alumno | 11 |

---

### Task 1: ADR de la arquitectura

**Files:**
- Create: `docs/internal/adr/0001-pipeline-serverless-orientado-a-eventos.md`

**Interfaces:**
- Consumes: spec de la Fase 2.
- Produces: ADR referenciable por el resto de la documentación (excepción del log group del Crawler).

- [ ] **Step 1: Crear el ADR**

```markdown
# ADR 0001 — Pipeline serverless orientado a eventos para el Lab 6

- **Estado:** Aceptado
- **Fecha:** 2026-10-04

## Contexto

El laboratorio de la Sesión 06 debe mostrar un pipeline serverless orientado a eventos y orquestado, con una Lambda empaquetada como imagen de contenedor, verificable con las herramientas de las Sesiones 4–5. El alumno despliega el stack ya construido y lo analiza en AWS. La plantilla actual de `infra/` solo contiene recursos de Glue Job y un bucket de artefactos.

## Decisión

1. Añadir S3 (con notificaciones a EventBridge), EventBridge, Step Functions Standard, Lambda (imagen), ECR, Glue Crawler/Data Catalog y un workgroup de Athena propio.
2. Organizar Terraform en módulos por servicio (`storage`, `registry`, `compute`, `orchestration`, `events`, `catalog`) bajo `infra/modules/`.
3. Desplegar el **estado final completo** (filtro `raw/*.csv`, Retry + Catch, Lambda desde imagen). Los bloques Modify y Container del spec v3 pasan a análisis guiado; Troubleshoot se mantiene con la variable `inject_fault`.
4. Publicar la imagen con `make deploy` en 3 pasos visibles (apply del ECR → build + push → apply completo), sin `local-exec` ni proveedores extra.
5. Retirar de la plantilla el bucket de artefactos y el rol de Glue Job, que ya no se usan.
6. **Excepción a AGENTS.md (log group del Crawler):** los Crawlers de Glue escriben en `/aws-glue/crawlers`, un log group compartido cuyo nombre no es configurable. El stack no lo declara para no colisionar con la Sesión 4 ni borrarlo en `destroy`. Los log groups de Lambda y Step Functions sí se declaran, con nombre propio y retención.

## Consecuencias

- Un solo `make deploy` deja el pipeline funcionando; requiere Docker activo.
- El `terraform apply -target=module.registry` del primer paso es deliberado y solo se usa en `deploy`.
- Los logs del Crawler no tienen retención gestionada por este stack.
- Cambiar la imagen exige un tag nuevo (ECR inmutable).
```

- [ ] **Step 2: Checkpoint**

Run: `ls docs/internal/adr/`
Expected: `0001-pipeline-serverless-orientado-a-eventos.md`

Commit (si hay git): `docs: ADR 0001 pipeline serverless orientado a eventos`

---

### Task 2: Lambda validadora (TDD)

**Files:**
- Create: `src/lambdas/__init__.py`, `src/lambdas/validator/__init__.py`, `src/lambdas/validator/app.py`
- Test: `tests/lambdas/test_validator.py`

**Interfaces:**
- Consumes: nada.
- Produces (usadas por Tasks 3, 5 y 10):
  - `validate_csv(key: str, text: str, required_columns: tuple[str, ...]) -> ValidationResult`
  - `ValidationResult(valid: bool, records: int = 0, reason: str | None = None)` (dataclass congelada)
  - `handler(event: dict, context: object) -> dict` → `{"valid": True, "records": int, "output": str}` o `{"valid": False, "reason": str}`
  - Env vars: `PROCESSED_PREFIX` (default `processed/orders/`), `REQUIRED_COLUMNS` (default `order_id,customer_id,amount,status`)
  - `_s3()` es el único punto de acceso a boto3 (los tests lo reemplazan con `monkeypatch`).
  - Razones de invalidez: `invalid_extension`, `empty_file`, `missing_columns: <a, b>`, `no_data_rows`, `invalid_amount: row <n>`, `invalid_encoding`.

- [ ] **Step 1: Crear los paquetes vacíos**

`src/lambdas/__init__.py`:
```python
"""AWS Lambda handlers."""
```
`src/lambdas/validator/__init__.py`:
```python
"""Validator Lambda."""
```

- [ ] **Step 2: Escribir los tests que fallan**

`tests/lambdas/test_validator.py`:
```python
from __future__ import annotations

import io

import pytest
from botocore.exceptions import ClientError

from src.lambdas.validator import app
from src.lambdas.validator.app import ValidationResult, validate_csv

REQUIRED = ("order_id", "customer_id", "amount", "status")
HEADER = "order_id,customer_id,amount,status\n"
VALID = HEADER + "1001,C001,150.50,COMPLETED\n1002,C002,320.00,COMPLETED\n"


def check(key: str, text: str) -> ValidationResult:
    return validate_csv(key, text, REQUIRED)


# --- validate_csv -----------------------------------------------------------


def test_valid_file_counts_records() -> None:
    assert check("raw/orders.csv", VALID) == ValidationResult(valid=True, records=2)


def test_extension_check_is_case_insensitive() -> None:
    assert check("raw/ORDERS.CSV", VALID).valid is True


def test_rejects_non_csv_extension() -> None:
    result = check("raw/prueba.json", VALID)
    assert result == ValidationResult(valid=False, reason="invalid_extension")


@pytest.mark.parametrize("text", ["", "   \n\n"])
def test_rejects_empty_file(text: str) -> None:
    assert check("raw/a.csv", text).reason == "empty_file"


def test_rejects_header_only_file() -> None:
    # Review focus 3: only a header, no data rows.
    result = check("raw/a.csv", HEADER)
    assert result == ValidationResult(valid=False, reason="no_data_rows")


def test_rejects_missing_column() -> None:
    text = "order_id,customer_id,status\n3001,C200,COMPLETED\n"
    assert check("raw/a.csv", text).reason == "missing_columns: amount"


def test_rejects_non_numeric_amount_reporting_the_row() -> None:
    text = HEADER + "1001,C001,150.50,COMPLETED\n1002,C002,abc,COMPLETED\n"
    assert check("raw/a.csv", text).reason == "invalid_amount: row 2"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity", "inf", "1_000", ""])
def test_rejects_amounts_decimal_accepts_but_athena_would_not(amount: str) -> None:
    # Review focus 5.
    text = HEADER + f"1001,C001,{amount},COMPLETED\n"
    assert check("raw/a.csv", text).reason == "invalid_amount: row 1"


def test_rejects_short_row_without_raising() -> None:
    # Review focus 4: fewer fields than the header.
    text = HEADER + "1001,C001\n"
    assert check("raw/a.csv", text).reason == "invalid_amount: row 1"


def test_accepts_amount_with_surrounding_spaces_and_negative_values() -> None:
    text = HEADER + "1001,C001, 10.5 ,COMPLETED\n1002,C002,-3,CANCELLED\n"
    assert check("raw/a.csv", text).valid is True


def test_accepts_text_that_still_carries_a_bom() -> None:
    # Review focus 1 (validation side).
    assert check("raw/a.csv", "﻿" + VALID).valid is True


# --- handler ----------------------------------------------------------------


class FakeS3:
    def __init__(self, objects: dict[str, bytes], put_error: Exception | None = None):
        self.objects = objects
        self.put_error = put_error
        self.puts: list[dict] = []

    def get_object(self, Bucket: str, Key: str) -> dict:
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, **kwargs) -> None:
        if self.put_error:
            raise self.put_error
        self.puts.append(kwargs)


def event(key: str, bucket: str = "lab-bucket") -> dict:
    return {"detail": {"bucket": {"name": bucket}, "object": {"key": key}}}


def install(monkeypatch: pytest.MonkeyPatch, fake: FakeS3) -> FakeS3:
    monkeypatch.setattr(app, "_s3", lambda: fake)
    return fake


def test_handler_writes_valid_file_with_the_same_name(monkeypatch) -> None:
    fake = install(monkeypatch, FakeS3({"raw/orders_2026_10_04.csv": VALID.encode()}))

    response = app.handler(event("raw/orders_2026_10_04.csv"), None)

    assert response == {
        "valid": True,
        "records": 2,
        "output": "processed/orders/orders_2026_10_04.csv",
    }
    assert len(fake.puts) == 1
    assert fake.puts[0]["Bucket"] == "lab-bucket"
    assert fake.puts[0]["Key"] == "processed/orders/orders_2026_10_04.csv"
    assert fake.puts[0]["Body"] == VALID.encode()


def test_handler_does_not_write_invalid_file(monkeypatch) -> None:
    fake = install(monkeypatch, FakeS3({"raw/bad.csv": (HEADER + "1,C,abc,X\n").encode()}))

    response = app.handler(event("raw/bad.csv"), None)

    assert response == {"valid": False, "reason": "invalid_amount: row 1"}
    assert fake.puts == []


def test_handler_flattens_nested_keys_to_the_base_name(monkeypatch) -> None:
    fake = install(monkeypatch, FakeS3({"raw/2026/10/a.csv": VALID.encode()}))

    response = app.handler(event("raw/2026/10/a.csv"), None)

    assert response["output"] == "processed/orders/a.csv"
    assert fake.puts[0]["Key"] == "processed/orders/a.csv"


def test_handler_keeps_spaces_and_special_characters_in_the_key(monkeypatch) -> None:
    # Review focus 2: EventBridge delivers the key without URL-encoding.
    key = "raw/orders 2026 10 (1).csv"
    fake = install(monkeypatch, FakeS3({key: VALID.encode()}))

    response = app.handler(event(key), None)

    assert response["output"] == "processed/orders/orders 2026 10 (1).csv"
    assert fake.puts[0]["Key"] == "processed/orders/orders 2026 10 (1).csv"


def test_handler_strips_the_bom_from_the_output(monkeypatch) -> None:
    # Review focus 1 (output side): a BOM would rename the first column.
    fake = install(monkeypatch, FakeS3({"raw/a.csv": b"\xef\xbb\xbf" + VALID.encode()}))

    response = app.handler(event("raw/a.csv"), None)

    assert response["valid"] is True
    assert fake.puts[0]["Body"] == VALID.encode()


def test_handler_rejects_files_that_are_not_utf8(monkeypatch) -> None:
    fake = install(monkeypatch, FakeS3({"raw/a.csv": b"\xff\xfe\x00\x01"}))

    response = app.handler(event("raw/a.csv"), None)

    assert response == {"valid": False, "reason": "invalid_encoding"}
    assert fake.puts == []


def test_handler_propagates_unexpected_errors_so_step_functions_can_catch_them(monkeypatch) -> None:
    denied = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "PutObject"
    )
    install(monkeypatch, FakeS3({"raw/a.csv": VALID.encode()}, put_error=denied))

    with pytest.raises(ClientError):
        app.handler(event("raw/a.csv"), None)


def test_handler_reads_configuration_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("PROCESSED_PREFIX", "out/")
    monkeypatch.setenv("REQUIRED_COLUMNS", "order_id,amount")
    text = "order_id,amount\n1,10.0\n"
    fake = install(monkeypatch, FakeS3({"raw/a.csv": text.encode()}))

    response = app.handler(event("raw/a.csv"), None)

    assert response == {"valid": True, "records": 1, "output": "out/a.csv"}
    assert fake.puts[0]["Key"] == "out/a.csv"
```

- [ ] **Step 3: Ejecutar los tests y verificar que fallan**

Run: `python scripts/testing/run_pytest.py tests/lambdas/test_validator.py -v`
Expected: error de colección `ModuleNotFoundError: No module named 'src.lambdas.validator.app'` (o `ImportError` de `validate_csv`).

- [ ] **Step 4: Implementar el handler**

`src/lambdas/validator/app.py`:
```python
"""Validator Lambda for the S6 serverless lab.

Receives the EventBridge "Object Created" event (forwarded as-is by Step
Functions), validates the CSV under raw/ and, if valid, writes it to
processed/orders/ under the SAME file name, so reprocessing a file never
duplicates data.

Validation problems are returned as {"valid": False, ...} (the Choice state
decides). Unexpected errors (e.g. AccessDenied on PutObject) are NOT caught on
purpose: they propagate so Step Functions' Catch stores them in $.error.

Keep this file self-contained: the container image copies only app.py.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from posixpath import basename

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_PROCESSED_PREFIX = "processed/orders/"
DEFAULT_REQUIRED_COLUMNS = "order_id,customer_id,amount,status"


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    records: int = 0
    reason: str | None = None


def _processed_prefix() -> str:
    return os.environ.get("PROCESSED_PREFIX", DEFAULT_PROCESSED_PREFIX)


def _required_columns() -> tuple[str, ...]:
    raw = os.environ.get("REQUIRED_COLUMNS", DEFAULT_REQUIRED_COLUMNS)
    return tuple(column.strip() for column in raw.split(",") if column.strip())


@lru_cache(maxsize=1)
def _s3():
    return boto3.client("s3")


def _invalid(reason: str) -> ValidationResult:
    return ValidationResult(valid=False, reason=reason)


def _is_numeric(value: str | None) -> bool:
    # Decimal also accepts "NaN", "Infinity" and "1_000"; Athena would not.
    if value is None or "_" in value:
        return False
    try:
        return Decimal(value.strip()).is_finite()
    except InvalidOperation:
        return False


def validate_csv(key: str, text: str, required_columns: tuple[str, ...]) -> ValidationResult:
    """Pure validation (no I/O). First failing rule wins."""
    if not key.lower().endswith(".csv"):
        return _invalid("invalid_extension")
    text = text.lstrip("﻿")
    if not text.strip():
        return _invalid("empty_file")

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    missing = [column for column in required_columns if column not in fieldnames]
    if missing:
        return _invalid("missing_columns: " + ", ".join(missing))

    rows = list(reader)
    if not rows:
        return _invalid("no_data_rows")
    for number, row in enumerate(rows, start=1):
        if not _is_numeric(row.get("amount")):
            return _invalid(f"invalid_amount: row {number}")
    return ValidationResult(valid=True, records=len(rows))


def handler(event: dict, context: object) -> dict:
    bucket = event["detail"]["bucket"]["name"]
    # EventBridge delivers the key as-is (S3 notifications URL-encode it; this does not).
    key = event["detail"]["object"]["key"]

    s3 = _s3()
    raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    try:
        text = raw.decode("utf-8-sig")  # also drops a leading BOM
    except UnicodeDecodeError:
        logger.info("s3://%s/%s is not valid UTF-8", bucket, key)
        return {"valid": False, "reason": "invalid_encoding"}

    result = validate_csv(key, text, _required_columns())
    if not result.valid:
        logger.info("s3://%s/%s rejected: %s", bucket, key, result.reason)
        return {"valid": False, "reason": result.reason}

    # debt: reads the whole file in memory; fine for small CSVs, revisit for
    # files of hundreds of MB (use streaming / Glue instead).
    output_key = _processed_prefix() + basename(key)
    s3.put_object(
        Bucket=bucket,
        Key=output_key,
        Body=text.encode("utf-8"),  # normalized: no BOM, so the Crawler reads clean headers
        ContentType="text/csv",
    )
    logger.info("s3://%s/%s -> %s (%d records)", bucket, key, output_key, result.records)
    return {"valid": True, "records": result.records, "output": output_key}
```

- [ ] **Step 5: Ejecutar los tests y verificar que pasan**

Run: `python scripts/testing/run_pytest.py tests/lambdas/test_validator.py -v`
Expected: todos PASS (≈ 24 tests).

- [ ] **Step 6: Lint**

Run: `make lint`
Expected: sin errores. Si ruff pide reformateo, corregir con `python scripts/testing/run_ruff_format.py` y repetir.

- [ ] **Step 7: Verificar que la imagen construye (solo si Docker Desktop está activo)**

Run: `make docker-build TAG=0.0.0-local`
Expected: termina con `naming to docker.io/library/validator:0.0.0-local`. Si el daemon está apagado (`failed to connect to the docker API`), anotar "pendiente: build" y continuar; se valida en Task 11.

- [ ] **Step 8: Checkpoint**

Commit (si hay git): `feat: validator lambda with pure csv validation`

---

### Task 3: Datos de prueba

**Files:**
- Create: `data/samples/orders_2026_10_04.csv`, `orders_2026_10_05.csv`, `orders_2026_10_06.csv`, `orders_invalid.csv`, `prueba.json`, `prueba.csv` (0 bytes), `prueba_invalida.csv`
- Modify: `.gitattributes` (añadir líneas al final)
- Test: `tests/lambdas/test_samples.py`

**Interfaces:**
- Consumes: `validate_csv`, `ValidationResult` (Task 2).
- Produces: rutas `data/samples/<nombre>` usadas por `make smoke` (Task 9), `tests/aws/test_stack.py` (Task 10) y la guía (Task 11).

- [ ] **Step 1: Escribir el test que falla**

`tests/lambdas/test_samples.py`:
```python
from __future__ import annotations

import csv
import io
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from src.lambdas.validator.app import validate_csv

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
REQUIRED = ("order_id", "customer_id", "amount", "status")
VALID_FILES = [
    ("orders_2026_10_04.csv", 3),
    ("orders_2026_10_05.csv", 2),
    ("orders_2026_10_06.csv", 2),
]


def read(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(("name", "records"), VALID_FILES)
def test_valid_samples_pass_validation(name: str, records: int) -> None:
    result = validate_csv(f"raw/{name}", read(name), REQUIRED)
    assert result.valid is True
    assert result.records == records


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("orders_invalid.csv", "invalid_amount: row 1"),
        ("prueba_invalida.csv", "missing_columns: amount"),
        ("prueba.csv", "empty_file"),
    ],
)
def test_invalid_samples_are_rejected(name: str, reason: str) -> None:
    assert validate_csv(f"raw/{name}", read(name), REQUIRED).reason == reason


def test_json_sample_is_rejected_by_extension() -> None:
    result = validate_csv("raw/prueba.json", read("prueba.json"), REQUIRED)
    assert result.reason == "invalid_extension"


def test_valid_samples_add_up_to_the_expected_athena_result() -> None:
    totals: dict[str, list] = defaultdict(lambda: [0, Decimal("0")])
    for name, _ in VALID_FILES:
        for row in csv.DictReader(io.StringIO(read(name))):
            totals[row["status"]][0] += 1
            totals[row["status"]][1] += Decimal(row["amount"])

    assert {status: tuple(values) for status, values in totals.items()} == {
        "COMPLETED": (6, Decimal("1290.75")),
        "CANCELLED": (1, Decimal("99.90")),
    }
```

- [ ] **Step 2: Verificar que falla**

Run: `python scripts/testing/run_pytest.py tests/lambdas/test_samples.py -v`
Expected: FAIL con `FileNotFoundError` en `data/samples/...`.

- [ ] **Step 3: Crear los archivos**

`data/samples/orders_2026_10_04.csv`:
```csv
order_id,customer_id,amount,status
1001,C001,150.50,COMPLETED
1002,C002,320.00,COMPLETED
1003,C003,125.00,COMPLETED
```
`data/samples/orders_2026_10_05.csv`:
```csv
order_id,customer_id,amount,status
1004,C004,210.00,COMPLETED
1005,C005,99.90,CANCELLED
```
`data/samples/orders_2026_10_06.csv`:
```csv
order_id,customer_id,amount,status
1006,C006,75.00,COMPLETED
1007,C007,410.25,COMPLETED
```
`data/samples/orders_invalid.csv`:
```csv
order_id,customer_id,amount,status
2001,C100,abc,COMPLETED
2002,C101,50.00,COMPLETED
```
`data/samples/prueba.json`:
```json
{}
```
`data/samples/prueba_invalida.csv`:
```csv
order_id,customer_id,status
3001,C200,COMPLETED
```
`data/samples/prueba.csv` debe quedar **vacío (0 bytes)**:

Run: `: > data/samples/prueba.csv && wc -c data/samples/prueba.csv`
Expected: `0 data/samples/prueba.csv`

- [ ] **Step 4: LF para los nuevos tipos de archivo**

Añadir al final de `.gitattributes`:
```text
*.csv text eol=lf
*.tf text eol=lf
*.tftpl text eol=lf
```

- [ ] **Step 5: Verificar que pasa**

Run: `python scripts/testing/run_pytest.py tests/lambdas -v`
Expected: todos PASS (Task 2 + Task 3).

- [ ] **Step 6: Checkpoint**

Commit (si hay git): `feat: lab sample files and expected-result tests`

---

### Task 4: Terraform raíz + módulos `storage` y `registry`

**Files:**
- Modify (reemplazo completo): `infra/main.tf`, `infra/variables.tf`, `infra/outputs.tf`, `infra/terraform.tfvars.example`
- Create: `infra/budget.tf`
- Create: `infra/modules/storage/{main,variables,outputs}.tf`, `infra/modules/registry/{main,variables,outputs}.tf`
- No tocar: `infra/providers.tf`, `infra/backend.tf.example`

**Interfaces:**
- Consumes: nada.
- Produces (usadas por Tasks 5–7):
  - Locals raíz: `local.name_prefix`, `local.account_id`, `local.raw_prefix` (`"raw/"`), `local.processed_prefix` (`"processed/orders/"`), `local.common_tags`
  - `module.storage` salidas: `bucket_name`, `bucket_arn`, `resource_arn`
  - `module.registry` salidas: `repository_url`, `repository_arn`, `resource_arn`
  - Variables raíz: `project_name`, `environment`, `owner`, `aws_region`, `tags`, `cost_center`, `log_retention_days`, `glue_database_name`, `image_tag`, `inject_fault`, y las del budget.

- [ ] **Step 1: Reemplazar `infra/variables.tf`**

```hcl
variable "project_name" {
  description = "Project name used in AWS resource naming."
  type        = string
  default     = "s6-lab"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "dev"
}

variable "owner" {
  description = "Owner tag applied to all managed resources."
  type        = string
  default     = "data-engineering"
}

variable "aws_region" {
  description = "AWS region for the deployment."
  type        = string
  default     = "us-east-1"
}

variable "tags" {
  description = "Additional tags applied to all resources."
  type        = map(string)
  default     = {}
}

variable "cost_center" {
  description = "Cost center tag for budget allocation and cost reporting."
  type        = string
  default     = "engineering"
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days. Use 7 for demos and labs; set higher for production per compliance requirements."
  type        = number
  default     = 7
}

variable "glue_database_name" {
  description = "Glue Data Catalog database that holds the lab table."
  type        = string
  default     = "s6_lab_db"
}

variable "image_tag" {
  description = "Tag of the validator image in ECR. The repository is tag-immutable: use a new tag for every image change."
  type        = string
  default     = "1.0.0"
}

variable "inject_fault" {
  description = "Troubleshooting scenario: when true, the Lambda role loses s3:PutObject on the processed prefix."
  type        = bool
  default     = false
}

variable "enable_budget_guardrail" {
  description = "Whether to create the monthly AWS Budget (and its SNS alert topic, if an email is set). Off by default for student/demo use; enable for real deployments."
  type        = bool
  default     = false
}

variable "budget_limit_usd" {
  description = "Monthly AWS budget limit in USD. Alerts fire at 80% (actual) and 100% (forecasted). Only used when enable_budget_guardrail is true."
  type        = number
  default     = 25
}

variable "budget_alert_email" {
  description = "Email address for budget alerts. Leave empty to skip SNS subscription creation. Only used when enable_budget_guardrail is true."
  type        = string
  default     = ""
}
```

- [ ] **Step 2: Crear `infra/budget.tf`** (los recursos de budget de la plantilla, movidos sin cambios de comportamiento)

```hcl
resource "aws_sns_topic" "budget_alerts" {
  count = var.enable_budget_guardrail && var.budget_alert_email != "" ? 1 : 0
  name  = "${local.name_prefix}-budget-alerts"
  tags  = local.common_tags
}

resource "aws_sns_topic_subscription" "budget_email" {
  count     = var.enable_budget_guardrail && var.budget_alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.budget_alerts[0].arn
  protocol  = "email"
  endpoint  = var.budget_alert_email
}

resource "aws_budgets_budget" "monthly" {
  count             = var.enable_budget_guardrail ? 1 : 0
  name              = "${local.name_prefix}-monthly-budget"
  budget_type       = "COST"
  limit_amount      = tostring(var.budget_limit_usd)
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2024-01-01_00:00"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$${var.project_name}"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.budget_alert_email != "" ? [var.budget_alert_email] : []
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.budget_alert_email != "" ? [var.budget_alert_email] : []
  }
}
```

- [ ] **Step 3: Reemplazar `infra/main.tf`** (por ahora solo `storage` y `registry`; las Tasks 5–7 añaden el resto)

```hcl
data "aws_caller_identity" "current" {}

locals {
  name_prefix      = lower(replace("${var.project_name}-${var.environment}", "_", "-"))
  account_id       = data.aws_caller_identity.current.account_id
  raw_prefix       = "raw/"
  processed_prefix = "processed/orders/"
  common_tags = merge(
    var.tags,
    {
      Project     = var.project_name
      Environment = var.environment
      Owner       = var.owner
      ManagedBy   = "Terraform"
      CostCenter  = var.cost_center
    }
  )
}

module "storage" {
  source      = "./modules/storage"
  bucket_name = "${local.name_prefix}-${local.account_id}-data"
  tags        = local.common_tags
}

module "registry" {
  source = "./modules/registry"
  name   = "${local.name_prefix}-validator"
  tags   = local.common_tags
}
```

- [ ] **Step 4: Reemplazar `infra/outputs.tf`**

```hcl
output "bucket_name" {
  description = "Data bucket (raw/ input, processed/ output)."
  value       = module.storage.bucket_name
}

output "ecr_repository_url" {
  description = "ECR repository URL for the validator image."
  value       = module.registry.repository_url
}

output "budget_name" {
  description = "AWS Budget name for monthly cost governance. Empty string when enable_budget_guardrail is false."
  value       = var.enable_budget_guardrail ? aws_budgets_budget.monthly[0].name : ""
}

output "budget_alert_sns_arn" {
  description = "SNS topic ARN for budget alerts. Empty string when the guardrail is disabled or no alert email is configured."
  value       = var.enable_budget_guardrail && var.budget_alert_email != "" ? aws_sns_topic.budget_alerts[0].arn : ""
}
```

- [ ] **Step 5: Reemplazar `infra/terraform.tfvars.example`**

```hcl
project_name = "s6-lab"
environment  = "dev"
aws_region   = "us-east-1"
owner        = "data-engineering"

# Default image tag used by `make deploy` is 1.0.0 (see DEPLOY_TAG in the Makefile).
# image_tag = "1.0.0"

tags = {
  CostCenter = "data-platform"
}
```

- [ ] **Step 6: Módulo `storage`**

`infra/modules/storage/variables.tf`:
```hcl
variable "bucket_name" {
  description = "Name of the data bucket."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
```
`infra/modules/storage/main.tf`:
```hcl
resource "aws_s3_bucket" "this" {
  bucket        = var.bucket_name
  force_destroy = true # lab: lets `terraform destroy` empty the bucket
  tags          = var.tags
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Sends "Object Created" events to the default EventBridge bus. It takes a few
# minutes to become effective after apply.
resource "aws_s3_bucket_notification" "this" {
  bucket      = aws_s3_bucket.this.id
  eventbridge = true
}
```
`infra/modules/storage/outputs.tf`:
```hcl
output "bucket_name" {
  description = "Data bucket name."
  value       = aws_s3_bucket.this.bucket
}

output "bucket_arn" {
  description = "Data bucket ARN."
  value       = aws_s3_bucket.this.arn
}

output "resource_arn" {
  description = "Primary resource ARN of this module (the bucket)."
  value       = aws_s3_bucket.this.arn
}
```

- [ ] **Step 7: Módulo `registry`**

`infra/modules/registry/variables.tf`:
```hcl
variable "name" {
  description = "ECR repository name."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
```
`infra/modules/registry/main.tf`:
```hcl
resource "aws_ecr_repository" "this" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE" # every image change needs a new tag
  force_delete         = true        # lab: lets `terraform destroy` remove a repo that holds images
  tags                 = var.tags
}

# Lets the Lambda service pull the image (spec section 13).
data "aws_iam_policy_document" "lambda_pull" {
  statement {
    sid    = "LambdaECRImageRetrievalPolicy"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
  }
}

resource "aws_ecr_repository_policy" "lambda_pull" {
  repository = aws_ecr_repository.this.name
  policy     = data.aws_iam_policy_document.lambda_pull.json
}
```
`infra/modules/registry/outputs.tf`:
```hcl
output "repository_url" {
  description = "Repository URL (without tag)."
  value       = aws_ecr_repository.this.repository_url
}

output "repository_arn" {
  description = "Repository ARN."
  value       = aws_ecr_repository.this.arn
}

output "resource_arn" {
  description = "Primary resource ARN of this module (the repository)."
  value       = aws_ecr_repository.this.arn
}
```

- [ ] **Step 8: Formatear y validar**

Run:
```bash
terraform -chdir=infra fmt -recursive
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
```
Expected: `Success! The configuration is valid.` (si `init` no puede descargar el provider por red, reportarlo al usuario; no continuar sin `validate`).

- [ ] **Step 9: Checkpoint**

Commit (si hay git): `feat(infra): root composition with storage and registry modules`

---

### Task 5: Módulo `compute` (Lambda + IAM + fallo inyectado)

**Files:**
- Create: `infra/modules/compute/{main,variables,outputs}.tf`
- Modify: `infra/main.tf` (añadir bloque), `infra/outputs.tf` (añadir salidas)

**Interfaces:**
- Consumes: `module.storage.bucket_arn`, `module.registry.repository_url`, `local.raw_prefix`, `local.processed_prefix`, `var.image_tag`, `var.inject_fault`, `var.log_retention_days`.
- Produces: `module.compute` salidas `function_arn`, `function_name`, `role_arn`, `resource_arn`, `log_group_name`, `log_group_arn`.

- [ ] **Step 1: `infra/modules/compute/variables.tf`**

```hcl
variable "name" {
  description = "Lambda function name (also used for the log group and role)."
  type        = string
}

variable "image_uri" {
  description = "Full image URI including tag, e.g. <repo-url>:1.0.0."
  type        = string
}

variable "bucket_arn" {
  description = "ARN of the data bucket the function reads from and writes to."
  type        = string
}

variable "raw_prefix" {
  description = "Input prefix the function may read (s3:GetObject)."
  type        = string
}

variable "processed_prefix" {
  description = "Output prefix the function may write (s3:PutObject)."
  type        = string
}

variable "required_columns" {
  description = "CSV columns the validator requires."
  type        = list(string)
  default     = ["order_id", "customer_id", "amount", "status"]
}

variable "inject_fault" {
  description = "When true, the role loses s3:PutObject on the processed prefix (troubleshooting scenario)."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
}

variable "memory_size" {
  description = "Lambda memory in MB."
  type        = number
  default     = 256
}

variable "timeout" {
  description = "Lambda timeout in seconds."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
```

- [ ] **Step 2: `infra/modules/compute/main.tf`**

```hcl
resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-exec"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "logs" {
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "${var.name}-logs"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.logs.json
}

# Read raw/*; write processed/orders/*. With inject_fault the write statement
# is omitted: the Lambda then fails with AccessDenied on PutObject, which is the
# Troubleshoot scenario (diagnose in $.error and CloudWatch, then `make fault-off`).
data "aws_iam_policy_document" "s3_access" {
  statement {
    sid       = "ReadRaw"
    actions   = ["s3:GetObject"]
    resources = ["${var.bucket_arn}/${var.raw_prefix}*"]
  }

  dynamic "statement" {
    for_each = var.inject_fault ? [] : [1]

    content {
      sid       = "WriteProcessed"
      actions   = ["s3:PutObject"]
      resources = ["${var.bucket_arn}/${var.processed_prefix}*"]
    }
  }
}

resource "aws_iam_role_policy" "s3_access" {
  name   = "${var.name}-s3-access"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.s3_access.json
}

resource "aws_lambda_function" "this" {
  function_name = var.name
  role          = aws_iam_role.this.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  architectures = ["x86_64"]
  memory_size   = var.memory_size
  timeout       = var.timeout

  environment {
    variables = {
      PROCESSED_PREFIX = var.processed_prefix
      REQUIRED_COLUMNS = join(",", var.required_columns)
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.this,
    aws_iam_role_policy.logs,
    aws_iam_role_policy.s3_access,
  ]

  tags = var.tags
}
```

- [ ] **Step 3: `infra/modules/compute/outputs.tf`**

```hcl
output "function_arn" {
  description = "Validator Lambda ARN."
  value       = aws_lambda_function.this.arn
}

output "function_name" {
  description = "Validator Lambda name."
  value       = aws_lambda_function.this.function_name
}

output "role_arn" {
  description = "Lambda execution role ARN."
  value       = aws_iam_role.this.arn
}

output "resource_arn" {
  description = "Primary resource ARN of this module (the function)."
  value       = aws_lambda_function.this.arn
}

output "log_group_name" {
  description = "CloudWatch log group name of the function."
  value       = aws_cloudwatch_log_group.this.name
}

output "log_group_arn" {
  description = "CloudWatch log group ARN of the function."
  value       = aws_cloudwatch_log_group.this.arn
}
```

- [ ] **Step 4: Añadir a `infra/main.tf`**

```hcl
module "compute" {
  source             = "./modules/compute"
  name               = "${local.name_prefix}-validator"
  image_uri          = "${module.registry.repository_url}:${var.image_tag}"
  bucket_arn         = module.storage.bucket_arn
  raw_prefix         = local.raw_prefix
  processed_prefix   = local.processed_prefix
  inject_fault       = var.inject_fault
  log_retention_days = var.log_retention_days
  tags               = local.common_tags
}
```

- [ ] **Step 5: Añadir a `infra/outputs.tf`**

```hcl
output "lambda_function_name" {
  description = "Validator Lambda name."
  value       = module.compute.function_name
}

output "log_group_name" {
  description = "CloudWatch log group name of the validator Lambda."
  value       = module.compute.log_group_name
}

output "log_group_arn" {
  description = "CloudWatch log group ARN of the validator Lambda."
  value       = module.compute.log_group_arn
}
```

- [ ] **Step 6: Formatear y validar**

Run:
```bash
terraform -chdir=infra fmt -recursive
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
```
Expected: `Success! The configuration is valid.`

- [ ] **Step 7: Checkpoint**

Commit (si hay git): `feat(infra): compute module with fault injection`

---

### Task 6: Módulo `orchestration` + plantilla ASL (TDD)

**Files:**
- Create: `infra/modules/orchestration/{main,variables,outputs}.tf`, `infra/modules/orchestration/pipeline.asl.json.tftpl`
- Test: `tests/infra/test_pipeline_asl.py`
- Modify: `infra/main.tf`, `infra/outputs.tf`

**Interfaces:**
- Consumes: `module.compute.function_arn`.
- Produces: `module.orchestration` salidas `state_machine_arn`, `state_machine_name`, `resource_arn`, `log_group_name`, `log_group_arn`. La plantilla recibe la variable `lambda_arn`.

- [ ] **Step 1: Escribir el test que falla**

`tests/infra/test_pipeline_asl.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "infra"
    / "modules"
    / "orchestration"
    / "pipeline.asl.json.tftpl"
)
LAMBDA_ARN = "arn:aws:lambda:us-east-1:123456789012:function:s6-lab-dev-validator"
RETRYABLE = {
    "Lambda.ServiceException",
    "Lambda.AWSLambdaException",
    "Lambda.SdkClientException",
    "Lambda.TooManyRequestsException",
}


@pytest.fixture(scope="module")
def asl() -> dict:
    text = TEMPLATE.read_text(encoding="utf-8").replace("${lambda_arn}", LAMBDA_ARN)
    return json.loads(text)


def test_starts_at_validate_and_invokes_the_lambda_with_the_whole_event(asl) -> None:
    assert asl["StartAt"] == "Validate"
    validate = asl["States"]["Validate"]
    assert validate["Resource"] == "arn:aws:states:::lambda:invoke"
    assert validate["Parameters"]["FunctionName"] == LAMBDA_ARN
    assert validate["Parameters"]["Payload.$"] == "$"
    assert validate["ResultPath"] == "$.validation"


def test_validate_retries_service_errors_with_backoff(asl) -> None:
    retry = asl["States"]["Validate"]["Retry"][0]
    assert set(retry["ErrorEquals"]) == RETRYABLE
    assert retry["IntervalSeconds"] == 2
    assert retry["MaxAttempts"] == 3
    assert retry["BackoffRate"] == 2.0


def test_validate_catches_everything_into_error_path(asl) -> None:
    catch = asl["States"]["Validate"]["Catch"][0]
    assert catch["ErrorEquals"] == ["States.ALL"]
    assert catch["ResultPath"] == "$.error"
    assert catch["Next"] == "HandleError"


def test_choice_routes_valid_results_to_success_and_defaults_to_invalid(asl) -> None:
    choice = asl["States"]["IsValid"]
    assert choice["Type"] == "Choice"
    rule = choice["Choices"][0]
    assert rule["Variable"] == "$.validation.Payload.valid"
    assert rule["BooleanEquals"] is True
    assert rule["Next"] == "PipelineSucceeded"
    assert choice["Default"] == "InvalidFile"


def test_terminal_states(asl) -> None:
    states = asl["States"]
    assert states["PipelineSucceeded"]["Type"] == "Succeed"
    assert states["InvalidFile"]["Type"] == "Fail"
    assert states["InvalidFile"]["Error"] == "InvalidFile"
    assert states["HandleError"]["Type"] == "Pass"
    assert states["HandleError"]["Next"] == "PipelineFailed"
    assert states["PipelineFailed"]["Type"] == "Fail"
    assert states["PipelineFailed"]["Error"] == "PipelineError"


def test_every_transition_targets_an_existing_state(asl) -> None:
    states = asl["States"]
    targets = [asl["StartAt"]]
    for state in states.values():
        targets += [state[key] for key in ("Next", "Default") if key in state]
        targets += [c["Next"] for c in state.get("Choices", [])]
        targets += [c["Next"] for c in state.get("Catch", [])]
    assert all(target in states for target in targets)
```

- [ ] **Step 2: Verificar que falla**

Run: `python scripts/testing/run_pytest.py tests/infra/test_pipeline_asl.py -v`
Expected: FAIL con `FileNotFoundError` en `pipeline.asl.json.tftpl`.

- [ ] **Step 3: Crear la plantilla ASL**

`infra/modules/orchestration/pipeline.asl.json.tftpl`:
```json
{
  "Comment": "Validates a CSV uploaded to raw/ and writes it to processed/orders/",
  "StartAt": "Validate",
  "States": {
    "Validate": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${lambda_arn}",
        "Payload.$": "$"
      },
      "ResultPath": "$.validation",
      "Retry": [
        {
          "ErrorEquals": [
            "Lambda.ServiceException",
            "Lambda.AWSLambdaException",
            "Lambda.SdkClientException",
            "Lambda.TooManyRequestsException"
          ],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error",
          "Next": "HandleError"
        }
      ],
      "Next": "IsValid"
    },
    "IsValid": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.validation.Payload.valid",
          "BooleanEquals": true,
          "Next": "PipelineSucceeded"
        }
      ],
      "Default": "InvalidFile"
    },
    "PipelineSucceeded": {
      "Type": "Succeed"
    },
    "InvalidFile": {
      "Type": "Fail",
      "Error": "InvalidFile",
      "Cause": "El archivo no cumple las reglas de validación"
    },
    "HandleError": {
      "Type": "Pass",
      "Next": "PipelineFailed"
    },
    "PipelineFailed": {
      "Type": "Fail",
      "Error": "PipelineError",
      "Cause": "Fallo inesperado; ver $.error"
    }
  }
}
```

- [ ] **Step 4: Verificar que pasa**

Run: `python scripts/testing/run_pytest.py tests/infra/test_pipeline_asl.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Módulo `orchestration`**

`infra/modules/orchestration/variables.tf`:
```hcl
variable "name" {
  description = "State machine name."
  type        = string
}

variable "lambda_arn" {
  description = "ARN of the Lambda invoked by the Validate state."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
```
`infra/modules/orchestration/main.tf`:
```hcl
# The /aws/vendedlogs/states/ prefix is the one recommended for Step Functions
# log groups (keeps the log-delivery resource policy small).
resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/vendedlogs/states/${var.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-sfn"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "invoke_lambda" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [var.lambda_arn]
  }
}

resource "aws_iam_role_policy" "invoke_lambda" {
  name   = "${var.name}-invoke-lambda"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.invoke_lambda.json
}

# The CloudWatch Logs log-delivery APIs do not support resource-level
# permissions, so Resource "*" is required here (and only here).
data "aws_iam_policy_document" "log_delivery" {
  statement {
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "log_delivery" {
  name   = "${var.name}-log-delivery"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.log_delivery.json
}

resource "aws_sfn_state_machine" "this" {
  name     = var.name
  role_arn = aws_iam_role.this.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/pipeline.asl.json.tftpl", {
    lambda_arn = var.lambda_arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.this.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  depends_on = [
    aws_iam_role_policy.invoke_lambda,
    aws_iam_role_policy.log_delivery,
  ]

  tags = var.tags
}
```
`infra/modules/orchestration/outputs.tf`:
```hcl
output "state_machine_arn" {
  description = "State machine ARN."
  value       = aws_sfn_state_machine.this.arn
}

output "state_machine_name" {
  description = "State machine name."
  value       = aws_sfn_state_machine.this.name
}

output "resource_arn" {
  description = "Primary resource ARN of this module (the state machine)."
  value       = aws_sfn_state_machine.this.arn
}

output "log_group_name" {
  description = "CloudWatch log group name of the state machine."
  value       = aws_cloudwatch_log_group.this.name
}

output "log_group_arn" {
  description = "CloudWatch log group ARN of the state machine."
  value       = aws_cloudwatch_log_group.this.arn
}
```

- [ ] **Step 6: Añadir a `infra/main.tf`**

```hcl
module "orchestration" {
  source             = "./modules/orchestration"
  name               = "${local.name_prefix}-pipeline"
  lambda_arn         = module.compute.function_arn
  log_retention_days = var.log_retention_days
  tags               = local.common_tags
}
```

- [ ] **Step 7: Añadir a `infra/outputs.tf`**

```hcl
output "state_machine_arn" {
  description = "Pipeline state machine ARN."
  value       = module.orchestration.state_machine_arn
}

output "state_machine_log_group_name" {
  description = "CloudWatch log group name of the state machine."
  value       = module.orchestration.log_group_name
}
```

- [ ] **Step 8: Formatear y validar**

Run:
```bash
terraform -chdir=infra fmt -recursive
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
python scripts/testing/run_pytest.py tests/infra -v
```
Expected: `Success! The configuration is valid.` y 6 PASS.

- [ ] **Step 9: Checkpoint**

Commit (si hay git): `feat(infra): orchestration module and ASL definition`

---

### Task 7: Módulos `events` y `catalog`

**Files:**
- Create: `infra/modules/events/{main,variables,outputs}.tf`, `infra/modules/catalog/{main,variables,outputs}.tf`
- Modify: `infra/main.tf`, `infra/outputs.tf`

**Interfaces:**
- Consumes: `module.storage.bucket_name`, `module.storage.bucket_arn`, `module.orchestration.state_machine_arn`, `local.processed_prefix`, `var.glue_database_name`.
- Produces: `module.events` salidas `rule_name`, `rule_arn`, `resource_arn`; `module.catalog` salidas `crawler_name`, `database_name`, `workgroup_name`, `results_bucket_name`, `resource_arn`.

- [ ] **Step 1: Módulo `events`**

`infra/modules/events/variables.tf`:
```hcl
variable "name" {
  description = "Rule name prefix."
  type        = string
}

variable "bucket_name" {
  description = "Bucket whose Object Created events trigger the pipeline."
  type        = string
}

variable "state_machine_arn" {
  description = "State machine started by the rule."
  type        = string
}

variable "key_pattern" {
  description = "EventBridge wildcard on the object key. Only raw/*.csv fires the pipeline; processed/ never does (no recursive invocation)."
  type        = string
  default     = "raw/*.csv"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
```
`infra/modules/events/main.tf`:
```hcl
# prefix+suffix is S3-native-notification syntax (AND). In an EventBridge
# pattern the values of an array are OR, so a content filter needs `wildcard`.
locals {
  event_pattern = {
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = { name = [var.bucket_name] }
      object = { key = [{ wildcard = var.key_pattern }] }
    }
  }
}

resource "aws_cloudwatch_event_rule" "this" {
  name          = "${var.name}-raw-csv"
  description   = "Starts the pipeline when a CSV lands in raw/"
  event_pattern = jsonencode(local.event_pattern)
  tags          = var.tags
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name}-events-to-sfn"
  assume_role_policy = data.aws_iam_policy_document.assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "start_execution" {
  statement {
    actions   = ["states:StartExecution"]
    resources = [var.state_machine_arn]
  }
}

resource "aws_iam_role_policy" "start_execution" {
  name   = "${var.name}-start-execution"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.start_execution.json
}

resource "aws_cloudwatch_event_target" "this" {
  rule     = aws_cloudwatch_event_rule.this.name
  arn      = var.state_machine_arn
  role_arn = aws_iam_role.this.arn
}
```
`infra/modules/events/outputs.tf`:
```hcl
output "rule_name" {
  description = "EventBridge rule name."
  value       = aws_cloudwatch_event_rule.this.name
}

output "rule_arn" {
  description = "EventBridge rule ARN."
  value       = aws_cloudwatch_event_rule.this.arn
}

output "resource_arn" {
  description = "Primary resource ARN of this module (the rule)."
  value       = aws_cloudwatch_event_rule.this.arn
}
```

- [ ] **Step 2: Módulo `catalog`**

`infra/modules/catalog/variables.tf`:
```hcl
variable "name" {
  description = "Name prefix for the crawler, role and Athena workgroup."
  type        = string
}

variable "bucket_name" {
  description = "Data bucket name."
  type        = string
}

variable "bucket_arn" {
  description = "Data bucket ARN."
  type        = string
}

variable "processed_prefix" {
  description = "Prefix the crawler scans (the table name is derived from its last folder, e.g. orders)."
  type        = string
}

variable "database_name" {
  description = "Glue Data Catalog database."
  type        = string
}

variable "results_bucket_name" {
  description = "Name of the Athena query results bucket."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
```
`infra/modules/catalog/main.tf`:
```hcl
# --- Data Catalog + Crawler -------------------------------------------------
# No log group is declared for the crawler on purpose: Glue crawlers write to
# the shared /aws-glue/crawlers group (name not configurable). See ADR 0001.

resource "aws_glue_catalog_database" "this" {
  name = var.database_name
  tags = var.tags
}

resource "aws_glue_classifier" "orders_csv" {
  name = "${var.name}-orders-csv"

  csv_classifier {
    contains_header = "PRESENT"
    delimiter       = ","
    quote_symbol    = "\""
  }
}

data "aws_iam_policy_document" "glue_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "crawler" {
  name               = "${var.name}-crawler"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "glue_service_role" {
  role       = aws_iam_role.crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

data "aws_iam_policy_document" "crawler_s3" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${var.bucket_arn}/${var.processed_prefix}*"]
  }

  statement {
    actions   = ["s3:ListBucket"]
    resources = [var.bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.processed_prefix}*"]
    }
  }
}

resource "aws_iam_role_policy" "crawler_s3" {
  name   = "${var.name}-crawler-s3"
  role   = aws_iam_role.crawler.id
  policy = data.aws_iam_policy_document.crawler_s3.json
}

# No schedule: the state machine starts it after every valid file (StartCrawler
# state); `make crawler-start` still works to run it by hand.
resource "aws_glue_crawler" "this" {
  name          = "${var.name}-orders"
  database_name = aws_glue_catalog_database.this.name
  role          = aws_iam_role.crawler.arn
  classifiers   = [aws_glue_classifier.orders_csv.name]

  s3_target {
    path = "s3://${var.bucket_name}/${var.processed_prefix}"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  depends_on = [
    aws_iam_role_policy_attachment.glue_service_role,
    aws_iam_role_policy.crawler_s3,
  ]

  tags = var.tags
}

# --- Athena -----------------------------------------------------------------

resource "aws_s3_bucket" "results" {
  bucket        = var.results_bucket_name
  force_destroy = true # lab: lets `terraform destroy` empty the bucket
  tags          = var.tags
}

resource "aws_s3_bucket_server_side_encryption_configuration" "results" {
  bucket = aws_s3_bucket.results.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "results" {
  bucket = aws_s3_bucket.results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_athena_workgroup" "this" {
  name          = "${var.name}-wg"
  force_destroy = true
  tags          = var.tags

  configuration {
    enforce_workgroup_configuration = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.results.bucket}/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
```
`infra/modules/catalog/outputs.tf`:
```hcl
output "crawler_name" {
  description = "Glue crawler name."
  value       = aws_glue_crawler.this.name
}

output "database_name" {
  description = "Glue Data Catalog database name."
  value       = aws_glue_catalog_database.this.name
}

output "workgroup_name" {
  description = "Athena workgroup name."
  value       = aws_athena_workgroup.this.name
}

output "results_bucket_name" {
  description = "Athena results bucket name."
  value       = aws_s3_bucket.results.bucket
}

output "resource_arn" {
  description = "Primary resource ARN of this module (the crawler)."
  value       = aws_glue_crawler.this.arn
}
```

- [ ] **Step 3: Añadir a `infra/main.tf`**

```hcl
module "events" {
  source            = "./modules/events"
  name              = local.name_prefix
  bucket_name       = module.storage.bucket_name
  state_machine_arn = module.orchestration.state_machine_arn
  tags              = local.common_tags
}

module "catalog" {
  source              = "./modules/catalog"
  name                = local.name_prefix
  bucket_name         = module.storage.bucket_name
  bucket_arn          = module.storage.bucket_arn
  processed_prefix    = local.processed_prefix
  database_name       = var.glue_database_name
  results_bucket_name = "${local.name_prefix}-${local.account_id}-athena-results"
  tags                = local.common_tags
}
```

- [ ] **Step 4: Añadir a `infra/outputs.tf`**

```hcl
output "event_rule_name" {
  description = "EventBridge rule that starts the pipeline."
  value       = module.events.rule_name
}

output "crawler_name" {
  description = "Glue crawler that catalogs processed/orders/."
  value       = module.catalog.crawler_name
}

output "glue_database_name" {
  description = "Glue Data Catalog database."
  value       = module.catalog.database_name
}

output "athena_workgroup" {
  description = "Athena workgroup for the lab."
  value       = module.catalog.workgroup_name
}
```

- [ ] **Step 5: Formatear y validar**

Run:
```bash
terraform -chdir=infra fmt -recursive
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
```
Expected: `Success! The configuration is valid.`

- [ ] **Step 6: Comprobar el contrato de outputs con el Makefile**

Run: `grep -E '^output "(ecr_repository_url|bucket_name|crawler_name|glue_database_name|athena_workgroup|state_machine_arn)"' infra/outputs.tf | wc -l`
Expected: `6`

- [ ] **Step 7: Checkpoint**

Commit (si hay git): `feat(infra): events and catalog modules`

---

### Task 8: Pruebas de guardarraíles sobre el HCL

**Files:**
- Test: `tests/infra/test_terraform_guardrails.py`

**Interfaces:**
- Consumes: todo `infra/**/*.tf` (Tasks 4–7).
- Produces: red de seguridad automática (`make test`) para las reglas de AGENTS.md y del spec.

- [ ] **Step 1: Escribir los tests**

`tests/infra/test_terraform_guardrails.py`:
```python
from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
MODULES = INFRA / "modules"
EXPECTED_MODULES = {"storage", "registry", "compute", "orchestration", "events", "catalog"}
TF_FILES = sorted(INFRA.rglob("*.tf"))


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def module_text(name: str) -> str:
    return "\n".join(text(p) for p in sorted((MODULES / name).glob("*.tf")))


def test_expected_modules_exist_and_expose_resource_arn() -> None:
    assert {p.name for p in MODULES.iterdir() if p.is_dir()} == EXPECTED_MODULES
    for name in EXPECTED_MODULES:
        assert 'output "resource_arn"' in text(MODULES / name / "outputs.tf"), name


def test_no_wildcard_iam_actions() -> None:
    for path in TF_FILES:
        for match in re.finditer(r"actions\s*=\s*\[([^\]]*)\]", text(path)):
            assert '"*"' not in match.group(1), f"wildcard action in {path}"


def test_wildcard_resource_is_only_the_step_functions_log_delivery() -> None:
    allowed = MODULES / "orchestration" / "main.tf"
    for path in TF_FILES:
        if re.search(r'resources\s*=\s*\["\*"\]', text(path)):
            assert path == allowed, f"unexpected Resource * in {path}"


def test_every_declared_log_group_has_retention() -> None:
    blocks = []
    for path in TF_FILES:
        blocks += re.findall(
            r'resource "aws_cloudwatch_log_group" "[^"]+" \{(.*?)\n\}', text(path), re.DOTALL
        )
    assert len(blocks) == 2  # lambda + step functions
    for body in blocks:
        assert "retention_in_days" in body


def test_log_groups_use_stack_specific_names_and_never_the_shared_glue_one() -> None:
    assert '"/aws/lambda/${var.name}"' in module_text("compute")
    assert '"/aws/vendedlogs/states/${var.name}"' in module_text("orchestration")
    assert not any(re.search(r'name\s*=\s*"/aws-glue/crawlers', text(p)) for p in TF_FILES)


def test_ecr_is_immutable_and_force_deletable() -> None:
    registry = module_text("registry")
    assert 'image_tag_mutability = "IMMUTABLE"' in registry
    assert re.search(r"force_delete\s*=\s*true", registry)


def test_lambda_runs_from_an_x86_image() -> None:
    compute = module_text("compute")
    assert 'package_type  = "Image"' in compute or 'package_type = "Image"' in compute
    assert '["x86_64"]' in compute


def test_fault_injection_removes_only_the_put_statement() -> None:
    compute = module_text("compute")
    assert 'dynamic "statement"' in compute
    assert "var.inject_fault ? [] : [1]" in compute
    assert "s3:PutObject" in compute


def test_event_rule_uses_wildcard_not_prefix_suffix() -> None:
    events = module_text("events")
    assert "wildcard" in events
    assert '"raw/*.csv"' in events
    # Comments may mention prefix/suffix; the pattern itself must not use them as keys.
    assert not re.search(r"\b(prefix|suffix)\s*=", events)


def test_s3_buckets_are_private_and_without_versioning() -> None:
    for name in ("storage", "catalog"):
        body = module_text(name)
        assert "block_public_policy     = true" in body
        assert "aws_s3_bucket_versioning" not in body


def test_budget_guardrail_is_opt_in() -> None:
    variables = text(INFRA / "variables.tf")
    match = re.search(
        r'variable "enable_budget_guardrail" \{.*?default\s*=\s*(\w+)', variables, re.DOTALL
    )
    assert match and match.group(1) == "false"
```

- [ ] **Step 2: Ejecutar**

Run: `python scripts/testing/run_pytest.py tests/infra -v && make lint`
Expected: todos PASS (6 de la Task 6 + 11 de esta), lint limpio. Si un test falla, el HCL de las Tasks 4–7 incumple una regla del spec: corregir el HCL, no el test.

- [ ] **Step 3: Checkpoint**

Commit (si hay git): `test(infra): guardrail tests for terraform`

---

### Task 9: Ajustes al Makefile

**Files:**
- Modify: `Makefile`

**Interfaces:**
- Consumes: outputs raíz `state_machine_arn`, `ecr_repository_url`, `bucket_name` (Tasks 4–7); `data/samples/orders_2026_10_04.csv` y `orders_invalid.csv` (Task 3); `src/lambdas/validator/app.py` (Task 2).
- Produces: targets `deploy`, `fault-on`, `fault-off`, `smoke`, `executions`; variable `DEPLOY_TAG`.

- [ ] **Step 1: Leer el Makefile actual**

Read `Makefile` completo (fue modificado en la Fase 1; basar las ediciones en su contenido real).

- [ ] **Step 2: Retirar el .zip**

Eliminar la línea `ZIP_PATH         ?= artifacts/validator.zip`, el nombre `package-zip` de la lista `.PHONY` y el target completo:
```make
package-zip: require-lambda-src ## Zip the validator handler (artifacts/validator.zip)
	mkdir -p $(dir $(ZIP_PATH))
	cd "$(dir $(LAMBDA_SRC))" && $(PYTHON) -m zipfile -c "$(CURDIR)/$(ZIP_PATH)" $(notdir $(LAMBDA_SRC))
```

- [ ] **Step 3: Añadir variables** (junto a `TAG ?=`)

```make
# Tag used by `deploy`, `fault-on` and `fault-off` (passed to Terraform as image_tag).
DEPLOY_TAG       ?= 1.0.0
```
y, junto a las demás lecturas de outputs:
```make
STATE_MACHINE_ARN ?= $(call tfout,state_machine_arn)
```
Actualizar también el comentario de cabecera que lista los outputs, añadiendo `state_machine_arn`.

- [ ] **Step 4: Añadir `deploy`, `fault-on`, `fault-off`, `smoke`, `executions` a `.PHONY`** y estos targets (antes de `# --- Quality`):

```make
# --- Lab flow ---------------------------------------------------------------
# The Lambda is created from an image, so the image must exist in ECR first:
# (1) create only the repository, (2) build + push, (3) apply everything.
deploy: ## Deploy in 3 visible steps: ECR repo -> image build+push -> full apply
	$(TF) init
	$(TF) apply -target=module.registry -var image_tag=$(DEPLOY_TAG)
	$(MAKE) docker-build docker-push TAG=$(DEPLOY_TAG)
	$(TF) apply -var image_tag=$(DEPLOY_TAG)

fault-on: ## Troubleshooting: remove s3:PutObject from the Lambda role
	$(TF) apply -var image_tag=$(DEPLOY_TAG) -var inject_fault=true

fault-off: ## Troubleshooting: restore the Lambda role
	$(TF) apply -var image_tag=$(DEPLOY_TAG) -var inject_fault=false

smoke: ## Upload the valid (F1) and the invalid sample to raw/
	$(MAKE) upload FILE=data/samples/orders_2026_10_04.csv
	$(MAKE) upload FILE=data/samples/orders_invalid.csv

executions: ## Last 10 executions of the state machine
	@test -n "$(STATE_MACHINE_ARN)" || { echo "STATE_MACHINE_ARN is empty: apply the stack first (output state_machine_arn)"; exit 1; }
	aws stepfunctions list-executions --region $(REGION) --state-machine-arn $(STATE_MACHINE_ARN) --max-items 10 --query 'executions[*].[name,status,startDate]' --output table
```

- [ ] **Step 5: Verificar con dry-runs**

Run:
```bash
make help
make -n deploy
make -n fault-on DEPLOY_TAG=1.0.1
make -n smoke
make executions
make -n docker-build TAG=1.0.0
```
Expected:
- `make help` lista `deploy`, `fault-on`, `fault-off`, `smoke`, `executions` y **no** lista `package-zip`.
- `make -n deploy` muestra, en orden: `terraform -chdir=infra init`, `... apply -target=module.registry -var image_tag=1.0.0`, `make docker-build docker-push TAG=1.0.0`, `... apply -var image_tag=1.0.0`.
- `make -n fault-on DEPLOY_TAG=1.0.1` incluye `-var image_tag=1.0.1 -var inject_fault=true`.
- `make executions` (sin stack) imprime `STATE_MACHINE_ARN is empty: ...` y sale con error.
- `make -n docker-build TAG=1.0.0` ya encuentra `app.py` (sin mensaje `Missing`).

- [ ] **Step 6: Checkpoint**

Commit (si hay git): `feat(make): deploy, fault injection, smoke and executions targets`

---

### Task 10: Tests `cloud` (estructura y extremo a extremo)

**Files:**
- Test: `tests/aws/test_stack.py`

**Interfaces:**
- Consumes: `tests/aws/aws_session.py::get_client(service)`; outputs raíz `bucket_name`, `lambda_function_name`, `state_machine_arn`, `state_machine_log_group_name`, `log_group_name`, `event_rule_name`; `data/samples/`.
- Produces: tests con marcador `cloud`, que se saltan sin credenciales o sin stack desplegado (`make test` los excluye con `-m "not cloud"`; se ejecutan con `python scripts/testing/run_cloud_tests.py`).

- [ ] **Step 1: Escribir los tests**

`tests/aws/test_stack.py`:
```python
"""Cloud tests for the deployed S6 stack (need credentials and `make deploy`).

Run with: python scripts/testing/run_cloud_tests.py
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from aws_session import get_client

pytestmark = pytest.mark.cloud

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "data" / "samples"
EXECUTION_TIMEOUT_SECONDS = 240  # S3 -> EventBridge propagation can take minutes
POLL_SECONDS = 5


@pytest.fixture(scope="module")
def outputs() -> dict[str, str]:
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        pytest.skip("AWS credentials not configured")
    result = subprocess.run(
        ["terraform", "-chdir=infra", "output", "-no-color", "-json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        data = {}
    if "state_machine_arn" not in data:
        pytest.skip("stack not deployed (run make deploy)")
    return {name: item["value"] for name, item in data.items()}


def wait_for_execution(sfn, arn: str, key: str, started_after: datetime) -> dict:
    deadline = time.monotonic() + EXECUTION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        for item in sfn.list_executions(stateMachineArn=arn, maxResults=20)["executions"]:
            if item["startDate"] < started_after:
                continue
            detail = sfn.describe_execution(executionArn=item["executionArn"])
            if key in detail["input"] and detail["status"] != "RUNNING":
                return detail
        time.sleep(POLL_SECONDS)
    pytest.fail(f"no finished execution for {key} within {EXECUTION_TIMEOUT_SECONDS}s")


def object_exists(s3, bucket: str, key: str) -> bool:
    return s3.list_objects_v2(Bucket=bucket, Prefix=key).get("KeyCount", 0) > 0


# --- structure --------------------------------------------------------------


def test_bucket_sends_events_to_eventbridge(outputs) -> None:
    config = get_client("s3").get_bucket_notification_configuration(Bucket=outputs["bucket_name"])
    assert "EventBridgeConfiguration" in config


def test_rule_only_matches_csv_files_in_raw(outputs) -> None:
    rule = get_client("events").describe_rule(Name=outputs["event_rule_name"])
    pattern = json.loads(rule["EventPattern"])
    assert pattern["detail"]["object"]["key"] == [{"wildcard": "raw/*.csv"}]


def test_lambda_is_an_x86_container_image(outputs) -> None:
    config = get_client("lambda").get_function_configuration(
        FunctionName=outputs["lambda_function_name"]
    )
    assert config["PackageType"] == "Image"
    assert config["Architectures"] == ["x86_64"]


def test_state_machine_has_retry_and_catch(outputs) -> None:
    sfn = get_client("stepfunctions")
    definition = json.loads(
        sfn.describe_state_machine(stateMachineArn=outputs["state_machine_arn"])["definition"]
    )
    validate = definition["States"]["Validate"]
    assert validate["Retry"] and validate["Catch"]


def test_log_groups_have_retention(outputs) -> None:
    logs = get_client("logs")
    for name in (outputs["log_group_name"], outputs["state_machine_log_group_name"]):
        groups = logs.describe_log_groups(logGroupNamePrefix=name)["logGroups"]
        group = next(g for g in groups if g["logGroupName"] == name)
        assert group.get("retentionInDays"), name


# --- end to end -------------------------------------------------------------


def test_valid_file_succeeds_and_is_written_to_processed(outputs) -> None:
    s3, sfn = get_client("s3"), get_client("stepfunctions")
    bucket = outputs["bucket_name"]
    started = datetime.now(timezone.utc)

    # Same key every time: reprocessing is idempotent and never adds rows.
    s3.upload_file(str(SAMPLES / "orders_2026_10_04.csv"), bucket, "raw/orders_2026_10_04.csv")
    detail = wait_for_execution(sfn, outputs["state_machine_arn"], "orders_2026_10_04.csv", started)

    assert detail["status"] == "SUCCEEDED"
    assert object_exists(s3, bucket, "processed/orders/orders_2026_10_04.csv")


def test_invalid_file_fails_with_invalid_file_and_writes_nothing(outputs) -> None:
    s3, sfn = get_client("s3"), get_client("stepfunctions")
    bucket = outputs["bucket_name"]
    name = f"e2e_{uuid.uuid4().hex[:8]}_orders_invalid.csv"  # unique: never pollutes the table
    started = datetime.now(timezone.utc)

    s3.upload_file(str(SAMPLES / "orders_invalid.csv"), bucket, f"raw/{name}")
    detail = wait_for_execution(sfn, outputs["state_machine_arn"], name, started)

    assert detail["status"] == "FAILED"
    assert detail["error"] == "InvalidFile"
    assert not object_exists(s3, bucket, f"processed/orders/{name}")
    s3.delete_object(Bucket=bucket, Key=f"raw/{name}")
```

- [ ] **Step 2: Verificar que se recoge y se salta sin credenciales/stack**

Run: `python scripts/testing/run_pytest.py tests/aws/test_stack.py -m cloud -v`
Expected: 9 SKIPPED (`AWS credentials not configured` o `stack not deployed`), 0 FAILED. Sin errores de importación (`aws_session` se resuelve porque `tests/aws/` queda en `sys.path`).

- [ ] **Step 3: Verificar que `make test` los excluye**

Run: `make test`
Expected: PASS; los tests de `tests/aws/test_stack.py` aparecen como `deselected`.

- [ ] **Step 4: Lint**

Run: `make lint`
Expected: limpio.

- [ ] **Step 5: Checkpoint**

Commit (si hay git): `test(aws): cloud tests for deployed stack`

---

### Task 11: Guía del alumno, verificación final y ensayo (usuario)

**Files:**
- Create: `docs/lab/guia_alumno.md`

**Interfaces:**
- Consumes: todos los targets del Makefile y los archivos de `data/samples/`.
- Produces: material del alumno y checklist de aceptación.

- [ ] **Step 1: Crear `docs/lab/guia_alumno.md`** (el bloque externo usa 4 backticks porque el contenido lleva bloques con 3)

````markdown
# Guía del alumno — Lab Sesión 06: Serverless, orquestación y contenedores

**Duración objetivo:** 45 min · **Idea central:** despliegas un pipeline ya construido y observas cómo interactúan los servicios en AWS.

```text
S3 raw/*.csv -> EventBridge -> Step Functions -> Lambda (imagen en ECR) -> S3 processed/orders/
                                                  verificación: Crawler -> Data Catalog -> Athena
```

## 0. Antes de la clase (pre-flight)

```bash
make preflight                                   # docker, aws, terraform y credenciales
docker pull public.ecr.aws/lambda/python:3.13    # evita esperar la descarga en clase
```

## 1. Deploy (10 min)

```bash
make deploy        # 3 pasos: repo ECR -> build + push de la imagen -> apply completo
make smoke         # sube orders_2026_10_04.csv (válido) y orders_invalid.csv
make executions    # últimas ejecuciones y su estado
```

Si `make executions` aún no muestra ejecuciones, espera 1–2 minutos: las notificaciones de S3 a EventBridge tardan en activarse.

Comprueba: el válido termina en `SUCCEEDED`, el inválido en `FAILED` (`InvalidFile`), y existe `processed/orders/orders_2026_10_04.csv`.

## 2. Explorar (10 min) — recorre el flujo en la consola

| Dónde | Qué mirar | Pregunta guía |
|---|---|---|
| EventBridge → Rules | El patrón de la regla (`wildcard: raw/*.csv`) | ¿Por qué no `prefix` + `suffix`? ¿Qué pasaría si la regla mirara todo el bucket? |
| Step Functions → ejecución | El input (`detail.bucket.name`, `detail.object.key`) y el grafo | ¿Qué decide el `Choice` y qué decide la Lambda? |
| Step Functions → definición | `Retry` y `Catch` del estado `Validate` | ¿Qué error se reintenta y cuál se captura? |
| Lambda → Imagen | Package type, arquitectura, URI de la imagen | ¿Quién ejecuta la imagen: ECR o Lambda? |
| ECR → repositorio | Tag y digest de la imagen | ¿Qué diferencia hay entre tag y digest? |
| IAM → rol de la Lambda | `GetObject` sobre `raw/*`, `PutObject` sobre `processed/orders/*` | ¿Por qué no hay `Action: "*"`? |

Puedes pedir ayuda a Claude Code para **explicar** un recurso o un archivo de `infra/`; no para reescribirlo.

## 3. Probar (5 min)

```bash
make upload FILE=data/samples/prueba.json                 # raw/prueba.json
make upload FILE=data/samples/prueba.csv PREFIX=otra/     # otra/prueba.csv
make upload FILE=data/samples/prueba_invalida.csv         # raw/prueba_invalida.csv
make executions
```

Predice antes de mirar: ¿cuáles disparan una ejecución y cuáles no? ¿Por qué?

## 4. Troubleshoot (7 min)

```bash
make fault-on                                             # el instructor rompe un permiso
make upload FILE=data/samples/orders_2026_10_06.csv       # F3
make executions
```

1. ¿En qué componente falló? Sigue la ruta: EventBridge ✓ (hay ejecución) → Step Functions ✓ → Lambda ✗.
2. Lee `$.error` en la ejecución y los logs de la Lambda en CloudWatch (`AccessDenied` en `PutObject`).
3. Identifica el recurso y la acción que faltan en la política del rol (`infra/modules/compute/main.tf`).

```bash
make fault-off                                            # restaura el permiso
make upload FILE=data/samples/orders_2026_10_06.csv       # misma clave: no duplica datos
```

## 5. Verify (8 min)

```bash
make upload FILE=data/samples/orders_2026_10_05.csv       # F2
make crawler-start
make crawler-status                                       # repite hasta READY
make athena-query
```

Resultado esperado (7 filas):

| status | filas | total |
|---|---:|---:|
| COMPLETED | 6 | 1290.75 |
| CANCELLED | 1 | 99.90 |

Los archivos inválidos y de prueba no aparecen. Opcional: vuelve a subir `orders_2026_10_04.csv`, repite la consulta y comprueba que los totales no cambian.

## 6. Cierre (5 min)

Responde 3 o 4: ¿Por qué EventBridge y no las notificaciones nativas de S3? ¿Qué administra AWS y qué administras tú? ¿Qué almacena ECR y quién ejecuta la imagen? ¿Qué pasa si el mismo evento llega dos veces? ¿Qué limitaciones tendría Lambda con archivos de varios GB?

Al terminar: `make tf-destroy` (cuesta poco, pero no lo dejes encendido).
````

- [ ] **Step 2: Verificación final automática**

Run:
```bash
make test
make lint
terraform -chdir=infra fmt -recursive -check
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
make help
```
Expected: `make test` y `make lint` verdes; `fmt -check` sin salida; `validate` → `Success! The configuration is valid.`; `make help` con 25 targets (sin `package-zip`).

- [ ] **Step 3: Ensayo en AWS (lo ejecuta el USUARIO; el agente no corre apply/destroy)**

Seguir `docs/lab/guia_alumno.md` en una cuenta de pruebas y comprobar los criterios de aceptación de la sección 11 del spec:

1. `make deploy` termina sin errores en cuenta limpia.
2. F1 → `Succeed`; `orders_invalid.csv` → `Fail` (`InvalidFile`).
3. `prueba.json` y `otra/prueba.csv` no disparan; `raw/prueba_invalida.csv` sí y falla.
4. `make fault-on` + F3 → `Fail` con `AccessDenied`; `make fault-off` + F3 → `Succeed`.
5. Athena: COMPLETED 6 / 1290.75 y CANCELLED 1 / 99.90.
6. Reprocesar F1 no cambia los totales.
7. `make ecr-digest TAG=1.0.0` muestra el digest.
8. `python scripts/testing/run_cloud_tests.py` pasa.
9. `make tf-destroy` limpia todo sin intervención manual.
10. El recorrido completo cabe en **45 min** (cronometrar; anotar el tiempo real de `make deploy` y del Crawler).

Anotar y reportar: tiempo de `docker build`/`push`, tipo de `amount` inferido por el Crawler, y si el `terraform apply -target` confunde en clase (riesgos R1, R3, R8 del spec).

- [ ] **Step 4: Checkpoint**

Commit (si hay git): `docs: student guide`

---

## Self-Review (hecha al escribir el plan)

**Cobertura del spec:**
- §1 decisiones → Tasks 1, 4–9. §3.1 S3 → T4. §3.2 EventBridge → T7. §3.3 ASL/logs → T6. §3.4 Lambda → T2. §3.5 Glue/Athena → T7. §4 datos → T3. §5 Terraform/IAM/fault → T4–T8. §6 deploy/Makefile → T9. §7 tiempo (45 min) → guía T11 y criterio 10. §8 pruebas → T2, T3, T6, T8, T10. §9 ADR y guía → T1, T11. §10 riesgos → ensayo T11. §11 criterios → T11 Step 4.
- Excepción del log group del Crawler: ADR (T1), test (T8), comentario en `catalog` (T7).

**Placeholders:** ninguno; todos los pasos de código llevan el código completo.

**Consistencia de tipos/nombres:** `validate_csv(key, text, required_columns)` y `ValidationResult` iguales en T2/T3; razones de invalidez idénticas en tests y guía; outputs raíz (`bucket_name`, `ecr_repository_url`, `crawler_name`, `glue_database_name`, `athena_workgroup`, `state_machine_arn`) coinciden con el contrato del Makefile; `event_rule_name`, `state_machine_log_group_name`, `lambda_function_name`, `log_group_name` coinciden con `tests/aws/test_stack.py`; la variable `lambda_arn` de la plantilla ASL coincide con el `templatefile` del módulo.

**Review Focus:** los 5 puntos tienen test (T2) y están marcados con comentarios `# Review focus N` en el código.
