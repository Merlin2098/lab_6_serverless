# Guía de Docker — Lab Sesión 06

Todo lo relacionado con la imagen de la Lambda: cómo se construye, cómo se publica en ECR, cómo probarla y cómo **renovar la sesión** cuando caduca. Para el deploy completo ver [guia_deploy.md](guia_deploy.md).

> **ECR almacena y distribuye la imagen; Lambda proporciona el compute serverless que la ejecuta.** No hay ECS ni EKS en este lab.

## 0. Antes de empezar: cargar las credenciales en la terminal

En **cada terminal Git Bash** donde vayas a trabajar con Docker (`make docker-build`, `make docker-push`, `make image-publish`, `make ecr-login`...), carga primero las credenciales de AWS, desde la raíz del repositorio:

```bash
set -a
source .env.credentials
set +a
```

Por qué hace falta: el Makefile y Docker no leen `.env.credentials`; el login a ECR se obtiene con las credenciales que existan en el **entorno** de esa terminal. Las variables cargadas solo valen para esa terminal: si abres otra, repite los tres comandos. Después comprueba que funcionan:

```bash
aws sts get-caller-identity
```

Debe mostrar tu cuenta. Si responde con `InvalidClientTokenId` o `ExpiredToken`, las credenciales del archivo caducaron: ver la sección 5.2.

## 1. Flujo

```text
Dockerfile --docker build--> imagen local --docker tag--> --docker push--> ECR --> Lambda (imagen)
```

Con el Makefile, cada paso es un target; todos muestran el comando real antes de ejecutarlo:

| Target | Comandos que ejecuta |
|---|---|
| `make ecr-login` | `aws ecr get-login-password ... \| docker login --username AWS --password-stdin <registry>` |
| `make docker-build TAG=1.0.0` | `docker build --platform linux/amd64 --provenance=false ... -t validator:1.0.0 .` |
| `make docker-push TAG=1.0.0` | `ecr-login`, luego `docker tag` y `docker push <repo>:1.0.0` |
| `make image-publish TAG=1.0.0` | `docker-build` + `docker-push`, **solo si el tag no está ya en ECR** |
| `make ecr-digest TAG=1.0.0` | `aws ecr describe-images` para ver tag y digest |

El paso 2 del deploy (ver [guia_deploy.md](guia_deploy.md#4-deploy)) es `make image-publish`. Los targets de imagen que necesitan el repositorio (`docker-push`, `image-publish`, `ecr-login`, `ecr-digest`) leen su URL del output `ecr_repository_url` de Terraform, así que el repositorio debe existir (el paso 1 del deploy, `terraform -chdir=infra apply -target=module.registry`, lo crea).

## 2. Los archivos

```text
docker/validator/Dockerfile                  # la imagen
docker/validator/Dockerfile.dockerignore     # qué entra al contexto de build
src/lambdas/validator/app.py                 # lo único que se copia a la imagen
```

- **Imagen base:** `public.ecr.aws/lambda/python:<versión>`. Incluye el Runtime Interface Client y boto3, así que no hay `requirements.txt`. Si el handler gana dependencias (por ejemplo Parquet en una extensión), se añaden al Dockerfile.
- **`CMD ["app.handler"]`:** apunta al handler del archivo copiado. `app.py` es autocontenido (sin imports relativos).
- **Contexto de build:** la raíz del repo. `Dockerfile.dockerignore` excluye todo salvo `app.py`, por lo que `.venv`, `.git`, `infra/` y los archivos `.env*` **no** entran al build.
- **Versión de Python:** `PYTHON_VERSION` (por defecto `3.13`). Debe ser un runtime vigente de Lambda; confírmalo antes de la clase. Para cambiarla: `make docker-build TAG=1.0.1 PYTHON_VERSION=3.14`.

## 3. Variables del Makefile relacionadas

| Variable | Por defecto | Uso |
|---|---|---|
| `TAG` | (sin valor) | Tag de la imagen para `docker-build`, `docker-push`, `image-publish`, `ecr-digest`. Obligatorio, nunca `latest` |
| `PYTHON_VERSION` | `3.13` | Versión de la imagen base |
| `PLATFORM` | `linux/amd64` | Arquitectura. Debe coincidir con la de la Lambda (`x86_64`) |
| `IMAGE_NAME` | `validator` | Nombre de la imagen local |
| `REGION` | `AWS_DEFAULT_REGION` o `us-east-1` | Región del registry |
| `REPO_URI` | output `ecr_repository_url` | Se puede forzar: `make docker-push TAG=1.0.0 REPO_URI=<cuenta>.dkr.ecr.us-east-1.amazonaws.com/<repo>` |

## 4. Tags, digest e inmutabilidad

El repositorio ECR es **inmutable**: un tag, una vez subido, no se puede sobrescribir. Consecuencias:

- Cada cambio de imagen exige un tag **nuevo**: `make image-publish TAG=1.0.1` y luego `terraform -chdir=infra apply -var image_tag=1.0.1`.
- Volver a hacer `docker push` del mismo tag falla con `tag invalid ... cannot be overwritten because the repository is immutable`. `make image-publish` lo evita al omitir el push si el tag existe.
> **Atención: repetir el deploy no actualiza código que ya fue publicado.** Si editas `app.py` después del primer deploy y repites `make image-publish TAG=1.0.0`, el tag `1.0.0` ya existe en ECR, `image-publish` omite el build y **tu cambio no llega a la Lambda**. Lo avisa con un mensaje al omitir el push, pero es fácil pasarlo por alto. Para publicar código nuevo, usa siempre un tag nuevo (siguiente sección).

### Cambiar el código de la Lambda

```bash
# 1. (opcional) probar la lógica sin Docker ni AWS
make test

# 2. construir y subir con un tag NUEVO
make image-publish TAG=1.0.1

# 3. apuntar la Lambda a la imagen nueva
terraform -chdir=infra apply -var image_tag=1.0.1
```

Desde ese momento pasa el mismo `-var image_tag=1.0.1` en cada `plan`/`apply` posterior (también al activar el fallo con `-var inject_fault=true`); con el valor por defecto (`1.0.0`) Terraform intentaría volver a la imagen anterior. Para no repetirlo, fíjalo en `infra/terraform.tfvars` con `image_tag = "1.0.1"`.

- **Tag vs digest:** el tag (`1.0.0`) es una etiqueta legible; el digest (`sha256:...`) identifica el contenido exacto de la imagen. `make ecr-digest TAG=1.0.0` imprime ambos; el digest también aparece al final de cada `docker push`.

## 5. Renovar la sesión

Hay **dos** sesiones distintas que caducan. Distinguirlas ahorra mucho tiempo.

### 5.1. Sesión de Docker con ECR (token de 12 horas)

`docker login` contra ECR usa un token que **vale 12 horas**. Cuando caduca, `docker push` o `docker pull` fallan con mensajes como:

```text
denied: Your authorization token has expired. Reauthenticate and try again.
no basic auth credentials
```

Para renovarla:

```bash
make ecr-login
```

Nota: `make docker-push` y `make image-publish` **ya ejecutan `ecr-login` cada vez**, así que dentro del Makefile la sesión se renueva sola. Renovarla a mano solo hace falta si usas `docker push` o `docker pull` directamente fuera del Makefile.

Equivalente manual (sustituye `<cuenta>` por tu ID de cuenta de 12 dígitos):

```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <cuenta>.dkr.ecr.us-east-1.amazonaws.com
```

Para cerrar la sesión: `docker logout <cuenta>.dkr.ecr.us-east-1.amazonaws.com`.

### 5.2. Credenciales de AWS (la causa más común de que falle el login)

Si `make ecr-login` falla con `password is empty`, o cualquier comando de `aws` con `InvalidClientTokenId` / `ExpiredToken` / `The security token included in the request is invalid`, no caducó el token de ECR: caducaron o son incorrectas **tus credenciales de AWS** (el login de ECR se obtiene con ellas).

1. Comprueba con qué identidad estás: `aws sts get-caller-identity`.
2. Obtén credenciales nuevas (según cómo accedas: consola, SSO o el instructor) y cárgalas en la terminal. Si las guardas en `.env.credentials` (formato `KEY=VALUE`, ver `.env.example`; incluye `AWS_SESSION_TOKEN` si son temporales), actualiza el archivo y recárgalas:

   ```bash
   set -a
   source .env.credentials
   set +a
   ```

3. Vuelve a comprobar `aws sts get-caller-identity` y entonces `make ecr-login`.

Atención: las variables de entorno **antiguas** tienen prioridad sobre un perfil nuevo. Si exportaste credenciales viejas en esta terminal y ahora usas otras, ciérrala y abre una nueva, o haz `unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN` antes de cargar las nuevas.

## 6. Probar la imagen en local (sin AWS)

```bash
make docker-build TAG=0.0.0-local
make docker-run-local TAG=0.0.0-local       # emulador de Lambda en localhost:9000 (deja la terminal ocupada)
```

En otra terminal:

```bash
make local-invoke PAYLOAD='{"detail":{"bucket":{"name":"x"},"object":{"key":"raw/a.csv"}}}'
```

Sirve para comprobar que la imagen arranca y que el handler carga. Como el contenedor no recibe credenciales de AWS, la invocación llegará hasta boto3 y devolverá un error de credenciales (`NoCredentialsError`): es lo esperado. La lógica de validación se prueba sin Docker con `make test`.

## 7. Problemas frecuentes

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `failed to connect to the docker API ... dockerDesktopLinuxEngine` | Docker Desktop apagado | Abrirlo y esperar a que arranque; comprobar con `docker version` |
| `TAG is required` | Falta el tag | `make docker-build TAG=1.0.0` |
| `REPO_URI is empty` | El repositorio aún no existe | Crearlo con el paso 1 del deploy (`apply -target=module.registry`) o pasar `REPO_URI=...` |
| `password is empty` / `InvalidClientTokenId` | Credenciales de AWS caducadas | Sección 5.2 |
| `denied: Your authorization token has expired` | Token de ECR (12 h) caducado | Sección 5.1: `make ecr-login` |
| `tag invalid ... repository is immutable` | Ese tag ya existe en ECR | Usa un tag nuevo, o `make image-publish`, que lo omite |
| Cambié `app.py`, repetí `make image-publish TAG=1.0.0` y la Lambda sigue con el código viejo | `image-publish` omitió el push porque `1.0.0` ya existía | Tag nuevo: `make image-publish TAG=1.0.1` y `terraform -chdir=infra apply -var image_tag=1.0.1` |
| `Source image ... does not exist` al crear la Lambda | La imagen no está en ECR | `make image-publish TAG=1.0.0` y luego repetir el `apply` completo |
| Lambda: `InvalidImage` | Imagen con atestaciones de `buildx` | El Makefile ya usa `--provenance=false`; si construyes a mano, añádelo |
| Lambda falla al invocar con `exec format error` | Arquitectura distinta de `x86_64` | Construir con `--platform linux/amd64` (el Makefile lo hace) |
| `docker push` muy lento la primera vez | Sube todas las capas de la base | Normal; las siguientes veces solo sube lo que cambia |

Reglas de Lambda para imágenes de contenedor: una sola arquitectura (no multi-arquitectura), solo Linux, ECR y Lambda en la **misma región**, y el repositorio permite el pull a `lambda.amazonaws.com` (`ecr:BatchGetImage` y `ecr:GetDownloadUrlForLayer`, ya configurado por Terraform).

## 8. Limpieza

- **En AWS:** `terraform -chdir=infra destroy` borra el repositorio ECR con sus imágenes (`force_delete`).
- **En tu máquina:** las imágenes locales no se borran solas:

  ```bash
  docker image ls validator                       # ver las imágenes locales del lab
  docker image rm validator:1.0.0                 # borrar una
  docker image rm <cuenta>.dkr.ecr.us-east-1.amazonaws.com/<repo>:1.0.0   # el alias con el nombre del registry
  ```
