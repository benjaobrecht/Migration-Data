SELECT
    YEAR("FECHA")  AS año,
    MONTH("FECHA") AS mes,
    COUNT(*)       AS registros
FROM proforma
GROUP BY 1, 2
ORDER BY 1, 2;
