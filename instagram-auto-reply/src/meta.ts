export interface MetaClient {
  privateReply(accountId: string, commentId: string, text: string): Promise<void>;
  publicReply(commentId: string, text: string): Promise<void>;
  refreshToken(): Promise<string>;
}

export class InstagramClient implements MetaClient {
  constructor(private token: string) {}
  private async post(path: string, body: object): Promise<void> {
    const response = await fetch(`https://graph.instagram.com/v21.0/${path}`, {
      method: 'POST', headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`Meta HTTP ${response.status}`);
  }
  async privateReply(accountId: string, commentId: string, text: string): Promise<void> {
    await this.post(`${encodeURIComponent(accountId)}/messages`, { recipient: { comment_id: commentId }, message: { text } });
  }
  async publicReply(commentId: string, text: string): Promise<void> {
    await this.post(`${encodeURIComponent(commentId)}/replies`, { message: text });
  }
  async refreshToken(): Promise<string> {
    const url = new URL('https://graph.instagram.com/refresh_access_token');
    url.searchParams.set('grant_type', 'ig_refresh_token');
    url.searchParams.set('access_token', this.token);
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Meta HTTP ${response.status}`);
    const data: unknown = await response.json();
    if (typeof data !== 'object' || data === null || !('access_token' in data) || typeof data.access_token !== 'string' || !data.access_token) throw new Error('Invalid refresh response');
    return data.access_token;
  }
}
