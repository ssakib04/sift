export type AudioChunk = {
  id?: number;
  speaker: string;
  startTime: number;
  endTime: number;
  data: ArrayBuffer;
};

const DB_NAME = "sift-interview-audio";
const STORE = "chunks";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE)) {
        request.result.createObjectStore(STORE, { autoIncrement: true });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export class ChunkBuffer {
  private memory: AudioChunk[] = [];
  private db: IDBDatabase | null = null;

  async open(): Promise<void> {
    try {
      this.db = await openDb();
      const stored = await this.readAll();
      this.memory.push(...stored);
    } catch {
      this.db = null;
    }
  }

  async add(chunk: AudioChunk): Promise<void> {
    const id = await this.put(chunk);
    this.memory.push({ ...chunk, id });
  }

  shift(): AudioChunk | undefined {
    return this.memory.shift();
  }

  unshift(chunk: AudioChunk): void {
    this.memory.unshift(chunk);
  }

  async remove(id: number | undefined): Promise<void> {
    if (!this.db || id === undefined) {
      return;
    }
    const db = this.db;
    await new Promise<void>((resolve) => {
      const transaction = db.transaction(STORE, "readwrite");
      transaction.objectStore(STORE).delete(id);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => resolve();
    });
  }

  private put(chunk: AudioChunk): Promise<number | undefined> {
    const db = this.db;
    if (!db) {
      return Promise.resolve(undefined);
    }
    return new Promise((resolve) => {
      const transaction = db.transaction(STORE, "readwrite");
      const request = transaction.objectStore(STORE).add({
        speaker: chunk.speaker,
        startTime: chunk.startTime,
        endTime: chunk.endTime,
        data: chunk.data,
      });
      request.onsuccess = () => resolve(Number(request.result));
      request.onerror = () => resolve(undefined);
    });
  }

  private readAll(): Promise<AudioChunk[]> {
    const db = this.db;
    if (!db) {
      return Promise.resolve([]);
    }
    return new Promise((resolve) => {
      const transaction = db.transaction(STORE, "readonly");
      const request = transaction.objectStore(STORE).openCursor();
      const chunks: AudioChunk[] = [];
      request.onsuccess = () => {
        const cursor = request.result;
        if (!cursor) {
          resolve(chunks);
          return;
        }
        const value = cursor.value as AudioChunk;
        chunks.push({ ...value, id: Number(cursor.key) });
        cursor.continue();
      };
      request.onerror = () => resolve([]);
    });
  }
}
