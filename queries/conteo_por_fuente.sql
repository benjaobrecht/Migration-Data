SELECT 'temusystem' AS fuente, COUNT(*) AS registros FROM temusystem
UNION ALL
SELECT 'proforma',             COUNT(*)               FROM proforma;
