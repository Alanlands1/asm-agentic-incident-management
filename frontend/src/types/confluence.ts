export interface ConfluenceConnection {
  site: string;
  connected: boolean;
  account_name?: string | null;
  error?: string | null;
  sync_minutes: number;
}

export interface ConfluenceSpace {
  key: string;
  id: string;
  name: string;
  selected: boolean;
}

export interface ConfluenceSync {
  id: number;
  trigger: "manual" | "schedule";
  spaces: string;
  started_at: string;
  finished_at?: string | null;
  pulled: number;
  created: number;
  updated: number;
  removed: number;
  error?: string | null;
}

export interface ConfluencePage {
  id: string;
  space_key: string;
  title: string;
  version: number;
  url?: string | null;
  synced_at: string;
}

export interface ConfluencePageDetail extends ConfluencePage {
  body: string;
}
