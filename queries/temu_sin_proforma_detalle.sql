WITH temu AS (
    SELECT * FROM temusystem
    WHERE "Expense Difference" <> 'No Difference'
       OR "Expense Difference" IS NULL
)
SELECT
    'en_temu_sin_proforma'                                                                         AS brecha,
    PRINTF('%04d-%02d', YEAR(t."Settlement month(eg:202305)"), MONTH(t."Settlement month(eg:202305)")) AS periodo,
    t."Tracking number"                                                                            AS id,
    t."Settlement month(eg:202305)"                                                                AS fecha,
    t."Expense Difference"                                                                         AS expense_difference
FROM temu t
LEFT JOIN proforma p ON t."Tracking number" = p."NROGUIA"
WHERE p."NROGUIA" IS NULL

ORDER BY periodo;
