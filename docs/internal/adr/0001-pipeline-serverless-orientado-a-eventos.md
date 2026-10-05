# ADR 0001 — Pipeline serverless orientado a eventos para el Lab 6

- **Estado:** Aceptado
- **Fecha:** 2026-10-04

## Contexto

El laboratorio de la Sesión 06 debe mostrar un pipeline serverless orientado a eventos y orquestado, con una Lambda empaquetada como imagen de contenedor, verificable con las herramientas de las Sesiones 4–5. El alumno despliega el stack ya construido y lo analiza en AWS. La plantilla actual de `infra/` solo contiene recursos de Glue Job y un bucket de artefactos.

## Decisión

1. Añadir S3 (con notificaciones a EventBridge), EventBridge, Step Functions Standard, Lambda (imagen), ECR, Glue Crawler/Data Catalog y un workgroup de Athena propio.
2. Organizar Terraform en módulos por servicio (`storage`, `registry`, `compute`, `orchestration`, `events`, `catalog`) bajo `infra/modules/`.
3. Desplegar el **estado final completo** (filtro `raw/*.csv`, Retry + Catch, Lambda desde imagen). Los bloques Modify y Container del spec v3 pasan a análisis guiado; Troubleshoot se mantiene con la variable `inject_fault`.
4. Publicar la imagen en 3 pasos visibles (apply del ECR → `make image-publish` → apply completo; Terraform se ejecuta directo, el Makefile solo envuelve Docker y AWS CLI), sin `local-exec` ni proveedores extra.
5. Retirar de la plantilla el bucket de artefactos y el rol de Glue Job, que ya no se usan.
6. **Excepción a AGENTS.md (log group del Crawler):** los Crawlers de Glue escriben en `/aws-glue/crawlers`, un log group compartido cuyo nombre no es configurable. El stack no lo declara para no colisionar con la Sesión 4 ni borrarlo en `destroy`. Los log groups de Lambda y Step Functions sí se declaran, con nombre propio y retención.

## Consecuencias

- Tres comandos visibles dejan el pipeline funcionando; requiere Docker activo.
- El `terraform apply -target=module.registry` del primer paso es deliberado y solo se usa en el primer deploy.
- Los logs del Crawler no tienen retención gestionada por este stack.
- Actualización: Step Functions inicia el Crawler tras cada archivo válido (estado `StartCrawler`, integración directa `glue:startCrawler`, sin Lambda). La ejecución no espera a que el Crawler termine, y un `CrawlerRunningException` se trata como éxito. El rol de la máquina de estados solo puede iniciar ese Crawler.
- Datos de prueba: `scripts/generate_orders.py` (`make gen-orders`) crea CSV nuevos con nombre de sufijo aleatorio (cada carga es una clave distinta en S3, sin sobrescribir muestras ni cargas previas) y `order_id` basado en la hora en milisegundos (sin ids repetidos entre ejecuciones, aunque se borre `data/generated/`).
- El Makefile ya no envuelve Terraform: se ejecuta con `terraform -chdir=infra ...`.
- Cambiar la imagen exige un tag nuevo (ECR inmutable).
