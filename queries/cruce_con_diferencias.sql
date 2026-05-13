WITH temu AS (
    SELECT * FROM temusystem
    WHERE "Expense Difference" <> 'No Difference'
       OR "Expense Difference" IS NULL
)
SELECT
    'en_temu_sin_proforma'                          AS brecha,
    YEAR(t."Settlement month(eg:202305)")           AS año,
    MONTH(t."Settlement month(eg:202305)")          AS mes,
    COUNT(*)                                        AS cantidad
FROM temu t
LEFT JOIN proforma p ON t."Tracking number" = p."NROGUIA"
WHERE p."NROGUIA" IS NULL
GROUP BY 1, 2, 3

UNION ALL

SELECT
    'en_proforma_sin_temu'  AS brecha,
    YEAR(p."FECHA")         AS año,
    MONTH(p."FECHA")        AS mes,
    COUNT(*)                AS cantidad
FROM proforma p
LEFT JOIN temu t ON p."NROGUIA" = t."Tracking number"
WHERE t."Tracking number" IS NULL
GROUP BY 1, 2, 3

ORDER BY brecha, año, mes;
