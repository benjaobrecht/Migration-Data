SELECT
    YEAR("Settlement month(eg:202305)")  AS año,
    MONTH("Settlement month(eg:202305)") AS mes,
    COUNT(*)                             AS registros
FROM temusystem
GROUP BY 1, 2
ORDER BY 1, 2;
