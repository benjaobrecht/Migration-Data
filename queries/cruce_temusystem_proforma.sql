SELECT
    t."Tracking number",
    t."Settlement month(eg:202305)" AS fecha_temu,
    p."FECHA"                       AS fecha_proforma
FROM temusystem t
JOIN proforma p ON t."Tracking number" = p."NROGUIA"
ORDER BY t."Settlement month(eg:202305)";
