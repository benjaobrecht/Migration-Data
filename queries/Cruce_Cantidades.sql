SELECT
    'en_temu_sin_proforma'                          AS brecha,
    YEAR(t."Settlement month(eg:202305)")           AS año,
    MONTH(t."Settlement month(eg:202305)")          AS mes,
    COUNT(*)                                        AS cantidad
FROM temusystem t
LEFT JOIN proforma p
       ON CAST(t."Tracking number" AS VARCHAR) = CAST(p."NROGUIA" AS VARCHAR)
WHERE p."NROGUIA" IS NULL
GROUP BY 1, 2, 3

UNION ALL

SELECT
    'en_proforma_sin_temu'  AS brecha,
    YEAR(p."FECHA")         AS año,
    MONTH(p."FECHA")        AS mes,
    COUNT(*)                AS cantidad
FROM proforma p
LEFT JOIN temusystem t
       ON CAST(p."NROGUIA" AS VARCHAR) = CAST(t."Tracking number" AS VARCHAR)
WHERE t."Tracking number" IS NULL
GROUP BY 1, 2, 3

ORDER BY brecha, año, mes;
