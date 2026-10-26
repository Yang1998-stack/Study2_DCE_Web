export interface Env {
  DB: D1Database;
  ASSETS: Fetcher;
  DCE_MODE?: string;
  DCE_ALLOW_FORMAL?: string;
  DCE_REQUIRE_INVITE?: string;
  ADMIN_USERNAME?: string;
  ADMIN_PASSWORD?: string;
  QUICKFORM_API_URL?: string;
  QUICKFORM_PILOT_API_URL?: string;
  QUICKFORM_FORMAL_ENABLED?: string;
  QUICKFORM_PILOT_ENABLED?: string;
  QUICKFORM_ALLOW_LOCAL_TEST?: string;
  QUICKFORM_TIMEOUT_SECONDS?: string;
  QUICKFORM_MAX_ATTEMPTS?: string;
  QUICKFORM_BACKOFF_SECONDS?: string;
}
export type Row = Record<string, any>;
export type Mode = 'demo' | 'pilot' | 'formal';
export type Alternative = 'A' | 'B' | 'N';
export interface Offer { origin: number; verification: number; quality: number; price: number; price_level?: number; product_volume_ml?: number }
export interface Task { id: string; block: string; seq: number; a: Offer; b: Offer }
export interface Design { config: Row; tasks: Task[]; byId: Record<string, Task>; byBlock: Record<string, Task[]> }
export interface Dataset { participants: Row[]; choices: Row[]; choice_long: Row[]; detail_views: Row[] }
