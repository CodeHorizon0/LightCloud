export interface CodeToken {
  text: string;
  classes: string;
}
export type CodeLine = CodeToken[];
export interface CodeRequest {
  source: string;
  language: string;
}
export interface CodeResult {
  lines: CodeLine[] | null;
}
