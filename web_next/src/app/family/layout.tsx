// 家属看板是纯客户端交互页（登录态存在 localStorage），
// 不能作为静态页被 CDN/代理长期缓存，否则发版后客户端仍会加载旧 HTML/旧 chunk。
// 强制动态渲染，使其返回 Cache-Control: no-store。
export const dynamic = 'force-dynamic';

export default function FamilyLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
