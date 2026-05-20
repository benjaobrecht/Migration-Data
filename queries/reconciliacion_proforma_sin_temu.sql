SELECT * FROM proforma
WHERE NOT EXISTS (
    SELECT 1 FROM temusystem t
    WHERE CAST(t."Tracking number" AS VARCHAR) = CAST(proforma."NROGUIA" AS VARCHAR)
)
ORDER BY "FECHA";
