export interface NativeHealthStatus {
  state: 'unavailable' | 'permission' | 'ready';
  source: 'health_connect' | 'healthkit';
  read_permission: 'granted' | 'unknown' | 'not_requested' | 'denied';
  message: string;
}
export const ZhijiHealth: {
  getStatus(): Promise<NativeHealthStatus>;
  requestAccess(): Promise<NativeHealthStatus>;
  read({ days }: { days: 7 | 30 }): Promise<{ readings: unknown[]; truncated: boolean; message?: string }>;
};
