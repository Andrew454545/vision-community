// SQLite supplies literals without converting 64-bit integers through JS.
// quote(REAL) uses too few digits for adjacent doubles; quote(TEXT) truncates
// embedded NULs. Keep both types exact in private offline recovery images.
export function sqliteLiteralRows(db, table, maximum = 10000) {
  const name = value => '"' + value.replaceAll('"', '""') + '"';
  const columns = db.prepare(`PRAGMA table_xinfo(${name(table)})`).all();
  if (!columns.length || columns.some(row => row.hidden !== 0)) throw Error('unsupported_sql_export_schema');
  // Bound SQLite-produced strings before fetching them into JS. Literal
  // escaping can double a row's bytes; the caller also checks final SQL size.
  const sizes = columns.map(column => `coalesce(length(CAST(${name(column.name)} AS BLOB)),0)`);
  if (db.prepare(`SELECT 1 FROM ${name(table)} WHERE (${sizes.join('+')})>100000 LIMIT 1`).get()) throw Error('sql_export_limit_exceeded');
  const selections = columns.map(({name: column}) => {
    const col = name(column);
    return `CASE WHEN typeof(${col})='real' THEN printf('%!.26g',${col})
      WHEN typeof(${col})='text' AND instr(${col},char(0))>0
      THEN 'CAST(X'''||hex(CAST(${col} AS BLOB))||''' AS TEXT)' ELSE quote(${col}) END AS ${col}`;
  });
  const rows = []; let bytes = 0;
  for (const row of db.prepare(`SELECT ${selections.join(',')} FROM ${name(table)}`).iterate()) {
    if (rows.length >= maximum) throw Error('sql_export_limit_exceeded');
    const values = columns.map(column => row[column.name]);
    // SQLite can contain infinities. They have no finite SQL numeric literal;
    // refuse them rather than silently changing a value or emitting invalid SQL.
    if (values.some(value => value === 'Inf' || value === '-Inf' || value === 'NaN')) throw Error('nonfinite_sql_export_value');
    const literal = values.join(','); bytes += Buffer.byteLength(literal);
    if (bytes > 16 * 1024 ** 2) throw Error('sql_export_limit_exceeded');
    rows.push(literal);
  }
  return {columns: columns.map(column => name(column.name)).join(','), rows: rows.sort()};
}
