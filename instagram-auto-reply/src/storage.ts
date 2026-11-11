export interface RecordEntry { comment_id: string; igsid: string; created_at: number }
export interface Storage {
  claim(record: RecordEntry): Promise<boolean>;
  cleanup(before: number): Promise<number>;
}

export class D1Storage implements Storage {
  constructor(private db: D1Database) {}
  async claim(record: RecordEntry): Promise<boolean> {
    const result = await this.db.prepare('INSERT OR IGNORE INTO replies (comment_id, igsid, created_at) VALUES (?, ?, ?)')
      .bind(record.comment_id, record.igsid, record.created_at).run();
    return (result.meta.changes ?? 0) > 0;
  }
  async cleanup(before: number): Promise<number> {
    const result = await this.db.prepare('DELETE FROM replies WHERE created_at < ?').bind(before).run();
    return result.meta.changes ?? 0;
  }
}

export class MemoryStorage implements Storage {
  readonly records = new Map<string, RecordEntry>();
  async claim(record: RecordEntry): Promise<boolean> {
    if (this.records.has(record.comment_id)) return false;
    this.records.set(record.comment_id, { ...record });
    return true;
  }
  async cleanup(before: number): Promise<number> {
    let count = 0;
    for (const [id, record] of this.records) if (record.created_at < before) { this.records.delete(id); count++; }
    return count;
  }
}
