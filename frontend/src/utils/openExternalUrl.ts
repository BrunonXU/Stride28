/**
 * 打开外部链接的统一入口
 *
 * 小红书链接现在带 xsec_token 参数，可以直接在浏览器中打开。
 */
export function openExternalUrl(url: string): void {
  window.open(url, '_blank', 'noopener,noreferrer')
}
