// Local SQLite adapter for finite migration/ledger fixtures. No remote access.
export function sqliteD1(sql, record=()=>{}) {
  return {prepare(query) {
    const statement=(args=[])=>({bind:(...bound)=>statement(bound),
      first:async()=>{record(query);return sql.prepare(query).get(...args)||null;},
      all:async()=>{record(query);return {results:sql.prepare(query).all(...args)};},
      run:async()=>{record(query);const r=sql.prepare(query).run(...args);return {success:true,meta:{changes:Number(r.changes)}};}});
    return statement();
  },async batch(statements) {
    sql.exec('BEGIN IMMEDIATE');
    try {const values=[];for(const statement of statements) values.push(await statement.run());sql.exec('COMMIT');return values;}
    catch(error) {sql.exec('ROLLBACK');throw error;}
  }};
}
