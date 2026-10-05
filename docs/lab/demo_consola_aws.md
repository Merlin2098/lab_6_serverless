# Recorro el pipeline por la consola de AWS — Lab Sesión 06

Con esta guía recorro, desde la **consola de AWS** y sin escribir código, cada servicio del pipeline y compruebo con mis propios ojos qué hace y por qué está ahí. En cada paso anoto dónde hago clic, qué debo ver y qué entiendo de lo que veo.

- **Tiempo:** ≈ 30 min.
- **Punto de partida:** el stack ya está desplegado (ver [guia_deploy.md](../deploy/guia_deploy.md#4-deploy)).
- **Mapa del pipeline:** [architecture.png](../architecture/architecture.png). Lo tengo abierto mientras avanzo.
- **Región de la consola:** **N. Virginia (us-east-1)**. Si no veo los recursos, lo primero que reviso es la región.

```text
S3 raw/*.csv -> EventBridge -> Step Functions -> Lambda (imagen en ECR) -> S3 processed/orders/
                                  y luego: StartCrawler -> Glue Crawler -> Data Catalog -> Athena
```

## 1. Antes de empezar

### Los nombres que voy a buscar
Los valores exactos los obtengo con `terraform -chdir=infra output` (el bucket y el repositorio llevan mi ID de cuenta):

| Recurso | Nombre |
|---|---|
| Bucket de datos (S3) | `s6-lab-dev-<account-id>-data` |
| Regla de EventBridge | `s6-lab-dev-raw-csv` |
| State machine | `s6-lab-dev-pipeline` |
| Lambda | `s6-lab-dev-validator` |
| Repositorio ECR | `s6-lab-dev-validator` |
| Crawler | `s6-lab-dev-orders` |
| Base del Data Catalog | `s6_lab_db` (tabla `orders`) |
| Workgroup de Athena | `s6-lab-dev-wg` |

### Mi checklist
- [ ] Tengo la sesión iniciada en la consola de AWS, en **us-east-1**.
- [ ] Abro una pestaña del navegador por servicio: **S3, EventBridge, Step Functions, Lambda, ECR, CloudWatch, Glue, Athena e IAM**.
- [ ] Tengo a mano los archivos de prueba de `data/samples/`: `orders_2026_10_04.csv`, `orders_2026_10_05.csv`, `orders_2026_10_06.csv`, `orders_invalid.csv`, `prueba.json` y `prueba.csv`.
- [ ] Tengo una terminal con las credenciales cargadas, para la parte de Troubleshoot (`terraform -chdir=infra apply -var inject_fault=true` y `... -var inject_fault=false`, o lo hace el instructor).

### Empiezo desde cero
Si ya hice pruebas antes, dejo el bucket limpio **desde la consola**:

1. S3 → bucket de datos → selecciono las carpetas `raw/` y `processed/` → **Delete** y confirmo.
2. **No borro el bucket** ni nada de los demás servicios.

Las ejecuciones antiguas de Step Functions siguen en la lista; no molestan, las ordeno por fecha de inicio. Si la tabla `orders` ya existía en el catálogo, se queda: cuando vuelva a lanzar el Crawler se actualiza.

## 2. El recorrido

### Paso 1 — Veo qué se desplegó (3 min)
**Dónde:** consola → **Resource Groups & Tag Editor** → **Tag Editor**.

1. Elijo la región `us-east-1` y el tipo de recurso **All supported resource types**.
2. Filtro por la etiqueta `Lab` con valor `serverless-orchestration-containers` → **Search resources**.
3. Miro la columna del tag `Component` (`storage`, `registry`, `compute`, `orchestration`, `events`, `catalog`).

**Qué debo ver:** el bucket, la Lambda, la state machine, el repositorio ECR, la regla de EventBridge, el Crawler, la base de Glue, el workgroup de Athena y los roles IAM.

**Qué entiendo:** todo lo que veo lo creó Terraform, y cada recurso lleva tags que identifican el lab y el módulo al que pertenece. Con el diagrama delante, ya sé qué quiero seguir: el camino de un archivo desde S3 hasta Athena.

### Paso 2 — Subo un archivo válido (4 min)
**Dónde:** **S3** → bucket de datos.

1. Si no existe, **Create folder** → nombre `raw` → Create.
2. Entro a `raw/` → **Upload** → **Add files** → `orders_2026_10_04.csv` → **Upload**.
3. Compruebo que el objeto quedó en `raw/orders_2026_10_04.csv`.

**Qué entiendo:** al subir el archivo, S3 genera un evento *Object Created* y lo envía a EventBridge. Yo no llamé a nada manualmente.

### Paso 2b — Veo en EventBridge quién decide qué dispara el pipeline (3 min)
**Dónde:** **Amazon EventBridge** → **Rules** → bus `default` → regla `s6-lab-dev-raw-csv`.

1. En la pestaña **Event pattern** localizo `"source": ["aws.s3"]`, `"detail-type": ["Object Created"]` y el filtro de la clave `{"wildcard": "raw/*.csv"}`.
2. En **Targets** veo que el destino es la state machine `s6-lab-dev-pipeline`, con un rol que solo permite `states:StartExecution`.

**Qué entiendo:**
- El filtro es de contenido: solo `.csv` dentro de `raw/`.
- La Lambda escribe en `processed/`, que **no** coincide con el patrón, así que el pipeline no puede dispararse a sí mismo.
- Uso `wildcard` y no prefijo más sufijo porque en un patrón de EventBridge los valores de una lista son un OR, no un AND como en las notificaciones nativas de S3.

### Paso 3 — Step Functions: veo la orquestación (5 min)
**Dónde:** **Step Functions** → **State machines** → `s6-lab-dev-pipeline` → pestaña **Executions**.

1. Abro la ejecución más reciente (tarda unos segundos en aparecer; recargo si hace falta). El estado es **Succeeded**.
2. En **Graph view** sigo el camino: `Validate` → `IsValid` → `StartCrawler` → `PipelineSucceeded`. `StartCrawler` es una llamada directa a Glue (integración con el SDK de AWS, sin Lambda): arranca el Crawler sin esperar a que termine.
3. Hago clic en `Validate`:
   - **Input**: es el evento completo de EventBridge (`detail.bucket.name`, `detail.object.key`).
   - **Output**: el resultado de la Lambda, `{"valid": true, "records": 3, "output": "processed/orders/orders_2026_10_04.csv"}`.
4. En la pestaña **Definition** localizo `Retry` (errores del servicio Lambda) y `Catch` (cualquier error inesperado se guarda en `$.error`).

**Qué entiendo:**
- Step Functions no valida nada: **coordina**. Quien decide si el archivo es válido es la Lambda; el `Choice` solo lee su respuesta.
- `Retry` sirve para errores recuperables; `Catch` para cuando ya no hay nada más que reintentar.

### Paso 4 — Lambda y la imagen de contenedor (4 min)
**Dónde:** **Lambda** → función `s6-lab-dev-validator`.

1. En la pestaña **Image** (o en la tarjeta de la función) veo el *Package type* **Image** y la URI del repositorio ECR con el tag `1.0.0`. En *Configuration → General* aparecen 256 MB y 30 s; la arquitectura es `x86_64`.
2. En **Monitor** → **View CloudWatch logs** abro el último log stream y encuentro la línea `... -> processed/orders/orders_2026_10_04.csv (3 records)`.
3. En **Configuration → Permissions** abro el rol de ejecución y leo la política: `s3:GetObject` sobre `raw/*` y `s3:PutObject` sobre `processed/orders/*`, y nada más.

**Qué entiendo:**
- No administro ningún servidor: AWS ejecuta la imagen. **ECR la almacena y Lambda la ejecuta.**
- El rol solo puede leer `raw/` y escribir `processed/orders/`: es el mínimo privilegio.

### Paso 5 — Compruebo el resultado en S3 (1 min)
**Dónde:** **S3** → `processed/orders/`.

**Qué debo ver:** el archivo `orders_2026_10_04.csv` con **el mismo nombre** que el original. Lo abro (**Open**) o lo descargo para confirmar que el contenido es el mismo.

**Qué entiendo:** la clave de salida es igual a la de entrada. Por eso, si el mismo evento llega dos veces (EventBridge entrega *al menos una vez*), el resultado no se duplica.

### Paso 6 — Pruebo un archivo inválido (3 min)
**Dónde:** **S3** → `raw/` → **Upload** → `orders_invalid.csv`.

1. En **Step Functions → Executions** abro la nueva ejecución: el estado es **Failed** con el error `InvalidFile`.
2. En el Graph view veo que el camino fue `IsValid` → `InvalidFile` (no pasó por el `Catch`).
3. En S3, `processed/orders/` **no** contiene nada de este archivo.

**Qué entiendo:** un archivo inválido no es una excepción. La Lambda responde `valid: false` y el `Choice` lo manda a `InvalidFile`. Esto es distinto de un error inesperado, que veré en el Paso 9: ese irá por el `Catch`.

### Paso 7 — Veo lo que NO debe disparar el pipeline (3 min)
**Dónde:** **S3**.

1. Subo `prueba.json` a `raw/`.
2. Creo la carpeta `otra` y subo `prueba.csv` ahí.
3. Espero ≈ 30 s y recargo **Step Functions → Executions**.

**Qué debo ver:** **ninguna ejecución nueva**. Antes de mirar, intento explicar por qué: el primero no es `.csv`, y el segundo no está en `raw/`.

**Qué entiendo:** el filtro de EventBridge actúa antes de que Step Functions se entere. Si la regla no coincide, no hay ejecución, no hay Lambda y no hay costo.

### Paso 8 — Tag y digest en ECR (2 min)
**Dónde:** **Amazon ECR** → **Private repositories** → `s6-lab-dev-validator`.

1. Veo la imagen con su tag `1.0.0`, el **digest** (`sha256:...`), el tamaño y la fecha de push.
2. En **Permissions** (política del repositorio) compruebo que el principal `lambda.amazonaws.com` puede hacer pull.

**Qué entiendo:**
- El tag es una etiqueta legible; el digest identifica el contenido exacto de la imagen.
- Este repositorio es **inmutable**: no puedo volver a subir `1.0.0`. Si cambio el código, necesito un tag nuevo.

### Paso 9 — Troubleshoot: provoco y diagnostico un fallo (6 min)
**Dónde:** terminal y consola.

1. **Terminal:** `terraform -chdir=infra apply -var inject_fault=true` (escribo `yes`). Quita a la Lambda el permiso `s3:PutObject`. Tarda ≈ 1 min.
2. **S3:** subo `orders_2026_10_06.csv` a `raw/`.
3. **Step Functions → Executions:** la ejecución termina en **Failed**, pero esta vez por la ruta de error: `Validate` → `HandleError` → `PipelineFailed`.
4. **Diagnostico**, siguiendo el camino: EventBridge ✓ (hay ejecución) → Step Functions ✓ (entró a `Validate`) → Lambda ✗.
5. Hago clic en `HandleError` → **Output**: en el campo `error` está el error que capturó el `Catch` (busco `AccessDenied`).
6. En **CloudWatch Logs** (desde la Lambda → Monitor → View CloudWatch logs) confirmo `AccessDenied` en la operación `PutObject`.
7. En **IAM** abro el rol de la Lambda y compruebo que **falta** `s3:PutObject` sobre `processed/orders/*`.
8. **Terminal:** `terraform -chdir=infra apply -var inject_fault=false` y **espero 20–30 s** (los cambios de IAM tardan en propagarse). Vuelvo a subir `orders_2026_10_06.csv`: ahora termina en **Succeeded**.

**Qué entiendo:** primero localizo *en qué componente* falló, luego leo el error, y por último corrijo el permiso concreto que falta. Nunca con `Action: "*"`.

### Paso 10 — Verifico el resultado: Crawler, catálogo y Athena (6 min)
Primero subo `orders_2026_10_05.csv` a `raw/`, para que estén los tres archivos válidos (F1, F2 y F3), y compruebo que su ejecución termina en **Succeeded**.

1. **Glue → Crawlers** → `s6-lab-dev-orders`: no lo ejecuto yo, lo inició Step Functions (estado `StartCrawler`) tras cada archivo válido. Miro **Last run** y espero a que el estado vuelva a **Ready** (puede tardar unos minutos). Si no lo ha hecho, compruebo la ejecución de `orders_2026_10_05.csv` en Step Functions.
2. **Glue → Databases → `s6_lab_db` → Tables → `orders`**: veo la ubicación (`processed/orders/`) y las columnas `order_id`, `customer_id`, `amount` y `status`.
3. **Athena → Query editor**: elijo el workgroup **`s6-lab-dev-wg`** y la base de datos **`s6_lab_db`**, y ejecuto:

   ```sql
   SELECT status, COUNT(*) AS filas, SUM(amount) AS total
   FROM s6_lab_db.orders
   GROUP BY status;
   ```

**Qué debo ver (7 filas en total):**

| status | filas | total |
|---|---:|---:|
| COMPLETED | 6 | 1290.75 |
| CANCELLED | 1 | 99.9 |

Athena puede mostrar `99.9` en lugar de `99.90`: es el mismo valor. Los archivos inválidos y de prueba **no aparecen**.

**Qué entiendo:** verifico con las herramientas de las sesiones 4 y 5, no con la Lambda. El catálogo y Athena son la prueba independiente de que el dato quedó bien.

### Paso 11 — Compruebo la idempotencia (1 min, opcional)
Vuelvo a subir `orders_2026_10_04.csv` a `raw/`, espero a que termine la ejecución y repito la consulta de Athena.

**Qué debo ver:** los totales **no cambian**.

## 3. Lo que debo poder explicar al terminar
Si puedo responder estas preguntas con mis palabras, entendí el lab:

1. ¿Por qué EventBridge y no las notificaciones nativas de S3?
2. ¿Qué decide el `Choice` y qué decide la Lambda?
3. ¿Qué error se resuelve con `Retry` y cuál con `Catch`?
4. ¿Qué almacena ECR y quién ejecuta la imagen? ¿Qué diferencia hay entre tag y digest?
5. ¿Qué parte de la infraestructura administra AWS y cuál administro yo?
6. ¿Qué pasa si el mismo evento llega dos veces?
7. ¿Qué limitaciones tendría Lambda con archivos de varios GB?

## 4. Si algo no sale como espero

| Qué me pasa | Causa probable | Qué hago |
|---|---|---|
| No aparece ninguna ejecución tras subir un CSV | Región equivocada; las notificaciones S3 → EventBridge aún no están activas; el archivo no está en `raw/` o no termina en `.csv` | Reviso la región y la ruta; espero 1–2 min tras un deploy reciente |
| Una ejecución sigue en **Running** | Arranque en frío de la Lambda | Espero unos segundos y recargo |
| Hice `fault-off` y la ejecución vuelve a fallar con `AccessDenied` | Propagación de IAM | Espero 30 s más y vuelvo a subir el archivo |
| El Crawler tarda | Es normal la primera vez | Mientras termina, repaso el catálogo de una ejecución anterior (`make e2e` deja la tabla creada) |
| Athena dice *No output location provided* o no encuentra la tabla | Elegí otro workgroup, o el Crawler aún no terminó su primera ejecución | Elijo `s6-lab-dev-wg` y espero a que el Crawler vuelva a **Ready** (puedo lanzarlo a mano con **Run**) |
| Athena devuelve más filas de las esperadas | Quedaron en `processed/orders/` archivos de pruebas anteriores | Borro los archivos extra de esa carpeta y vuelvo a ejecutar el Crawler (**Run**) |
| No veo un servicio en la consola | Mi sesión no tiene permisos | Pido una sesión con permisos de lectura sobre los servicios del lab |

## 5. Lo mismo, desde la terminal
Todo lo anterior también puedo hacerlo con `make`: `make smoke`, `make gen-orders` y `make upload-generated` (para datos nuevos), `make upload FILE=...`, `make executions`, `make crawler-status`, `make athena-query`. El Troubleshoot y el destroy se hacen con Terraform directo (`-var inject_fault=true/false`, `terraform -chdir=infra destroy`). Y `make e2e` ejecuta de una vez una verificación completa con el SDK de Python. Ver [guia_deploy.md](../deploy/guia_deploy.md).

## 6. Al terminar
`terraform -chdir=infra destroy` (escribo `yes`) elimina todo el stack. Cuesta muy poco tenerlo encendido, pero no lo dejo olvidado.
