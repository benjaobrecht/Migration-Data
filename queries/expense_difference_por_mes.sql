SELECT "Expense Difference", COUNT(*) AS cantidad
FROM temusystem
WHERE MONTH("Settlement month(eg:202305)") = 3
GROUP BY 1
UNION ALL
SELECT 'TOTAL', COUNT(*)
FROM temusystem
WHERE MONTH("Settlement month(eg:202305)") = 3
ORDER BY 2 DESC;
