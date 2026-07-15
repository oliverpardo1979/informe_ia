# Informe CJC sobre IA y empleo

Este repositorio contiene un borrador técnico reproducible sobre exposición ocupacional a inteligencia artificial generativa en Colombia durante 2025.

## Reproducción

1. Ubique `BaseIA.dta` en `../CJC-Monitor/Datos/Processed/` y la correlativa en `../CJC-Monitor/DocumentacionAuxiliar/`.
2. Ejecute `code/01_analisis_exposicion_ia_2025.py` para regenerar tablas y figuras.
3. Ejecute `code/02_generar_informe_pdf.py` para producir `output/pdf/informe_ia_cjc_2025.pdf`.

Las rutas pueden modificarse con `BASE_IA_PATH`, `IA_CROSSWALK_PATH` y `CJC_MONITOR_ROOT`.

## Criterios metodológicos

- Estimación principal: correspondencia exacta de `OFICIO_C8` con CIUO-08 a cuatro dígitos.
- Imputación a dos dígitos: sólo sensibilidad, nunca resultado principal.
- Ponderación: factor de expansión `fex`.
- Ingreso mensual equivalente: ingreso real por hora por horas semanales por `52/12`.
- Los empates de ingreso permanecen juntos al formar quintiles y percentiles.
- La exposición OIT mide capacidad tecnológica sobre tareas; no mide efectos causales sobre empleo o salarios.

## Pendientes para publicación

- Reconstruir el universo completo de ocupados de 2025: la base disponible suma 22,96 millones frente a 23,83 millones en el promedio anual oficial.
- Conservar `P3042` para desagregar educación en doce niveles.
- Revisar manualmente los códigos colombianos sin equivalencia exacta.
- Incorporar errores estándar con el diseño muestral de la GEIH.

El archivo `main.tex` contiene la fuente editorial en LaTeX. `references.bib` reúne las referencias principales.
