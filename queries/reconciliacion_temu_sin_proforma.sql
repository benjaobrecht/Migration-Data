SELECT * FROM temusystem
WHERE ("Expense Difference" <> 'No Difference' OR "Expense Difference" IS NULL)
  AND NOT EXISTS (
      SELECT 1 FROM proforma p
      WHERE CAST(p."NROGUIA" AS VARCHAR) = CAST(temusystem."Tracking number" AS VARCHAR)
  )
ORDER BY "Settlement month(eg:202305)";
