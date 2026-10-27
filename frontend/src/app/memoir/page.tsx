import { redirect } from 'next/navigation';

/** 回忆录已合并进「人生之书」的「素材库」栏，旧地址保留跳转。 */
export default function MemoirPage() {
  redirect('/book?tab=memoir');
}
