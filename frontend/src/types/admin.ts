export type SettingValue = string | number | boolean | null | string[];

export interface AdminSetting {
  key: string;
  value: SettingValue;
  baseline: SettingValue;
  overridden: boolean;
  editable: boolean;
}

export interface AdminYaml {
  name: string;
  overridden: boolean;
  text: string;
}

/** A reference document as the backend parses it: the same shape as the YAML file. */
export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

export interface AdminDocument {
  name: string;
  overridden: boolean;
  document: Json;
}

export interface AdminChange {
  id: number;
  kind: "setting" | "document";
  key: string;
  old_value: unknown;
  new_value: unknown;
  claimed_by: string;
  changed_at: string;
}
