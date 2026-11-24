// zen-agent — portable memory: newline-delimited JSON, no database, no lock-in.
import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import { dirname } from 'node:path';

export interface MemoryEvent {
  ts: string;
  kind: 'route' | 'tool' | 'answer' | 'note' | 'denied';
  [key: string]: unknown;
}

export class MemoryStore {
  constructor(private readonly path: string) {}

  append(event: Omit<MemoryEvent, 'ts'> & { ts?: string }): MemoryEvent {
    const record: MemoryEvent = { ts: event.ts ?? new Date().toISOString(), ...event } as MemoryEvent;
    mkdirSync(dirname(this.path), { recursive: true });
    appendFileSync(this.path, `${JSON.stringify(record)}\n`);
    return record;
  }

  read(limit = 20): MemoryEvent[] {
    if (!existsSync(this.path)) return [];
    return readFileSync(this.path, 'utf8')
      .split('\n')
      .filter((line) => line.trim() !== '')
      .slice(-limit)
      .map((line) => JSON.parse(line) as MemoryEvent);
  }

  /** Cheap lexical recall: the events that mention the words in the query, most recent first. */
  recall(query: string, limit = 5): MemoryEvent[] {
    const words = query.toLowerCase().split(/\s+/).filter((w) => w.length > 2);
    return this.read(500)
      .filter((e) => {
        const hay = JSON.stringify(e).toLowerCase();
        return words.some((w) => hay.includes(w));
      })
      .slice(-limit)
      .reverse();
  }
}
