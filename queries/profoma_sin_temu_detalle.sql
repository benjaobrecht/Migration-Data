WITH temu AS (
    SELECT * FROM temusystem
    WHERE "Expense Difference" <> 'No Difference'
       OR "Expense Difference" IS NULL
)
SELECT
    'en_proforma_sin_temu'                                          AS brecha,
    PRINTF('%04d-%02d', YEAR(p."FECHA"), MONTH(p."FECHA"))          AS periodo,
    p."NROGUIA"                                                     AS id,
    p."FECHA"                                                       AS fecha
FROM proforma p
LEFT JOIN temu t ON p."NROGUIA" = t."Tracking number"
WHERE t."Tracking number" IS NULL

ORDER BY periodo;
