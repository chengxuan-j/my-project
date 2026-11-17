/**
 * 演示脚本：写死的「老人说一句 → 小忆回一句」。
 *
 * 用途只有一个——现场演示时不依赖模型，也不会因为网络或额度出岔子。
 * 两条使用路径：
 *   1. 点「演示脚本」自动播放，按节奏把整段对话铺出来；
 *   2. 手动输入台词原文（完全一致），小忆也会照脚本回答，不走模型。
 *
 * 文案要求：口语、短句、有年代感；小忆的回应只做两件事——顺着往下问、
 * 或提一件老人刚说过的事，**不要写「听着就…」这类套话**。
 */

export interface DemoScriptTurn {
  role: 'user' | 'assistant';
  content: string;
  /** 这一幕的开头（只打在老人第一句上），用于在对话里显示分幕，也方便日后做短片分段 */
  scene?: string;
}

export interface DemoScript {
  id: string;
  title: string;
  subtitle: string;
  turns: DemoScriptTurn[];
}

/** 长剧本：50 句（25 个来回），约 1 分半。 */
const RESERVOIR: DemoScript = {
  id: 'reservoir',
  title: '十七岁那年修水库',
  subtitle: '50 句 · 25 个来回 · 苦日子里的人和情分',
  turns: [
    { role: 'user', content: '我十七岁那年跟着生产队去修水库，天没亮就出发。' },
    { role: 'assistant', content: '那地方远吗？' },
    { role: 'user', content: '远，走了三十多里地，到的时候天都黑了。' },
    { role: 'assistant', content: '头一晚是怎么睡的？' },
    { role: 'user', content: '住席棚，地上铺稻草，十几个人挤一块。' },
    { role: 'assistant', content: '席棚里那个冬天不好过吧？' },
    { role: 'user', content: '冷，被子薄，半夜常常冻醒。' },
    { role: 'assistant', content: '冻醒了怎么办？' },
    { role: 'user', content: '就起来烤火，火堆边坐一会儿再躺下。' },
    { role: 'assistant', content: '工地上吃什么？' },
    { role: 'user', content: '窝头咸菜，有时候是高粱面，能吃饱就不错了。' },
    { role: 'assistant', content: '干活累不累？' },
    { role: 'user', content: '累，抬石头，肩膀磨破了皮。' },
    { role: 'assistant', content: '磨破了还接着干？' },
    { role: 'user', content: '那时候都这样，谁也不好意思说歇着。' },
    { role: 'assistant', content: '有没有撑不住的时候？' },
    { role: 'user', content: '有一回发烧，烧到三十九度，老王把他的棉袄给我盖上。' },
    { role: 'assistant', content: '老王是跟您一块去的？' },
    { role: 'user', content: '嗯，隔壁村的，比我大两岁，人实在。' },
    { role: 'assistant', content: '后来您俩一直有来往吗？' },
    { role: 'user', content: '水库修完就各回各的村，头几年还托人带过话。' },
    { role: 'assistant', content: '再后来呢？' },
    { role: 'user', content: '再后来听说他去了东北，一直没见着。' },
    { role: 'assistant', content: '您还惦记着他？' },
    { role: 'user', content: '惦记。前年他儿子来电话，说老王走了。' },
    { role: 'assistant', content: '您听见消息那会儿，心里头咋想的？' },
    { role: 'user', content: '我坐了半天没说话，觉得这辈子的一个见证人没了。' },
    { role: 'assistant', content: '后来您去送他了吗？' },
    { role: 'user', content: '没去成，路太远，这事一直搁在心里。' },
    { role: 'assistant', content: '水库修了多久？' },
    { role: 'user', content: '两年多，我在那儿过的十八岁生日。' },
    { role: 'assistant', content: '生日那天怎么过的？' },
    { role: 'user', content: '老王给我煮了两个鸡蛋，就算过生日了。' },
    { role: 'assistant', content: '有没有特别想家的时候？' },
    { role: 'user', content: '想，夜里躺着听风声，就想我妈做的面条。' },
    { role: 'assistant', content: '修完回家那天什么样？' },
    { role: 'user', content: '走到村口，我妈站在那儿，头发白了不少。' },
    { role: 'assistant', content: '她看见您说了什么？' },
    { role: 'user', content: '就说回来了，然后进屋给我擀面。' },
    { role: 'assistant', content: '那碗面什么味道？' },
    { role: 'user', content: '香，一辈子忘不了。' },
    { role: 'assistant', content: '后来您还回去看过那个水库吗？' },
    { role: 'user', content: '前些年去过一次，水还在，人都不在了。' },
    { role: 'assistant', content: '站在坝上想起什么？' },
    { role: 'user', content: '想起那些抬石头的日子，想起老王。' },
    { role: 'assistant', content: '那段日子对您来说意味着什么？' },
    { role: 'user', content: '苦是苦，可那时候人实在，心里踏实。' },
    { role: 'assistant', content: '今天这段讲下来，心里松快些吗？' },
    { role: 'user', content: '松快，说出来像放下点东西。' },
    { role: 'assistant', content: '那把它存下来吧，往后还能翻出来看。' },
  ],
};

/** 短剧本：30 句（15 个来回），约 1 分钟。 */
const SEWING_MACHINE: DemoScript = {
  id: 'sewing-machine',
  title: '母亲那台缝纫机',
  subtitle: '30 句 · 15 个来回 · 一台机器和一个人的手艺',
  turns: [
    { role: 'user', content: '我妈有一台蝴蝶牌缝纫机，是 1981 年买的。' },
    { role: 'assistant', content: '那时候买缝纫机不容易吧？' },
    { role: 'user', content: '不容易，攒了三年的钱，还托人弄的票。' },
    { role: 'assistant', content: '买回来那天家里什么样？' },
    { role: 'user', content: '全村人都来看，我妈笑得合不拢嘴。' },
    { role: 'assistant', content: '她手艺好吗？' },
    { role: 'user', content: '好，村里人做衣服都找她，过年最忙。' },
    { role: 'assistant', content: '做一件衣服要多久？' },
    { role: 'user', content: '一条裤子半天，一件褂子一天。' },
    { role: 'assistant', content: '收钱吗？' },
    { role: 'user', content: '不收钱，人家送点鸡蛋、白面。' },
    { role: 'assistant', content: '您小时候穿过她做的衣服？' },
    { role: 'user', content: '穿过，我的棉袄都是她做的，针脚密。' },
    { role: 'assistant', content: '哪件您记得最清楚？' },
    { role: 'user', content: '一件蓝布褂子，我上中专那年做的。' },
    { role: 'assistant', content: '穿着它去报到？' },
    { role: 'user', content: '嗯，第一次离家，我妈送我到村口。' },
    { role: 'assistant', content: '她说了什么？' },
    { role: 'user', content: '就说在外面吃饱，别舍不得花钱。' },
    { role: 'assistant', content: '您当时什么感觉？' },
    { role: 'user', content: '没敢回头，怕她看见我掉眼泪。' },
    { role: 'assistant', content: '后来那台缝纫机呢？' },
    { role: 'user', content: '一直在家里，我妈走了以后我收起来了。' },
    { role: 'assistant', content: '现在还能用吗？' },
    { role: 'user', content: '能用，我去年还踩过，声音还是那个声音。' },
    { role: 'assistant', content: '踩起来的时候想起什么？' },
    { role: 'user', content: '想起她坐在窗边，脚一下一下地踩。' },
    { role: 'assistant', content: '那画面您记得真清楚。' },
    { role: 'user', content: '清楚，一闭眼就在眼前。' },
    { role: 'assistant', content: '这段讲得真好，要不要存下来做成短片？' },
  ],
};

/**
 * 情节剧本：68 句（34 个来回）· 五幕 · 约 2 分钟。
 *
 * 和上面两份的区别：不是"回忆访谈"，而是一条能当故事看的线——
 * 起（父亲半夜发病）→ 承（一个人走三十里夜路）→ 转（卫生院求人、钱不够）
 * → 合（父亲得救、多年后还钱、陈大夫去世）。
 * 每一幕都有地点、天气、动作、物件（手电、雪粒子、自行车、药箱、鸡蛋），
 * 后面接分镜时可以直接拆成画面。
 */
const NIGHT_ROAD: DemoScript = {
  id: 'night-road',
  title: '三十里夜路请大夫',
  subtitle: '68 句 · 5 幕 · 有起承转合，适合直接拆分镜',
  turns: [
    { role: 'user', content: '我十三岁那年冬天，后半夜我爸突然喊肚子疼，在炕上打滚。', scene: '第一幕 · 后半夜的炕' },
    { role: 'assistant', content: '那天家里就您和您妈？' },
    { role: 'user', content: '就我俩，我哥在外地当兵，赶不回来。' },
    { role: 'assistant', content: '大夫在哪儿？' },
    { role: 'user', content: '公社卫生院，离我们村三十里山路。' },
    { role: 'assistant', content: '那时候没电话吧？' },
    { role: 'user', content: '没有，只能人去。我妈给我披上棉袄，说快去快回。' },
    { role: 'assistant', content: '出门的时候带了什么？' },
    { role: 'user', content: '一个手电筒，两个凉窝头，我妈塞给我的。' },
    { role: 'assistant', content: '外头什么天？' },

    { role: 'user', content: '下着雪粒子，风刮在脸上跟刀子一样。', scene: '第二幕 · 三十里夜路' },
    { role: 'assistant', content: '一个人走夜路，怕不怕？' },
    { role: 'user', content: '怕。路过坟地那一段，我一边走一边唱歌壮胆。' },
    { role: 'assistant', content: '唱的什么？' },
    { role: 'user', content: '《学习雷锋好榜样》，跑调了也不敢停。' },
    { role: 'assistant', content: '走了多久？' },
    { role: 'user', content: '走到一半，手电筒没电了。' },
    { role: 'assistant', content: '那怎么走？' },
    { role: 'user', content: '摸黑走，靠记性认路，摔了两跤，膝盖磕破了。' },
    { role: 'assistant', content: '摔了还接着走？' },
    { role: 'user', content: '不敢停。一停更冷，也怕自己就不敢走了。' },
    { role: 'assistant', content: '脑子里想什么？' },
    { role: 'user', content: '就想我爸疼成那样，我要是回不去，他怎么办。' },
    { role: 'assistant', content: '后来看见人家了吗？' },

    { role: 'user', content: '看见卫生院那盏灯的时候，我眼泪一下就下来了。', scene: '第三幕 · 卫生院那盏灯' },
    { role: 'assistant', content: '敲门有人应吗？' },
    { role: 'user', content: '敲了半天，值班大夫披着衣服出来，问我干啥。' },
    { role: 'assistant', content: '您怎么说？' },
    { role: 'user', content: '我说我爸肚子疼得打滚，求您去看看吧。' },
    { role: 'assistant', content: '他去了吗？' },
    { role: 'user', content: '他犹豫，说夜里路不好走，也没车。' },
    { role: 'assistant', content: '那您怎么求他的？' },
    { role: 'user', content: '我给他跪下了，说您不去我爸就没命了。' },
    { role: 'assistant', content: '他扶您起来了吗？' },
    { role: 'user', content: '扶了，回屋背起药箱，说走。' },
    { role: 'assistant', content: '回来的路上呢？' },
    { role: 'user', content: '他骑一辆旧自行车，我坐后头给他打手电。' },
    { role: 'assistant', content: '手电不是没电了吗？' },

    { role: 'user', content: '卫生院给换了两节电池。风大，我一只手举着，一只手抓着他棉袄。', scene: '第四幕 · 天亮之后' },
    { role: 'assistant', content: '到家的时候什么样？' },
    { role: 'user', content: '天刚蒙蒙亮，我妈站在门口，脸都冻白了。' },
    { role: 'assistant', content: '大夫怎么说？' },
    { role: 'user', content: '说是急性阑尾炎，再晚就没命了，得赶紧送县医院。' },
    { role: 'assistant', content: '县医院更远吧？' },
    { role: 'user', content: '更远，得用拖拉机。陈大夫又帮着找车。' },
    { role: 'assistant', content: '钱够吗？' },
    { role: 'user', content: '不够。我妈把柜子里攒的钱都拿出来，还差二十块。' },
    { role: 'assistant', content: '那二十块怎么凑的？' },
    { role: 'user', content: '陈大夫从兜里掏的，说先救人，钱以后再说。' },
    { role: 'assistant', content: '您妈当时什么反应？' },
    { role: 'user', content: '她要给他磕头，被他拉住了。' },
    { role: 'assistant', content: '后来手术顺利吗？' },

    { role: 'user', content: '顺利。我爸住了半个月院，拣回一条命。', scene: '第五幕 · 三十年后的还愿' },
    { role: 'assistant', content: '那位陈大夫后来还见过吗？' },
    { role: 'user', content: '见过。第二年开春，我妈带着我，提一篮子鸡蛋去还钱。' },
    { role: 'assistant', content: '他收了吗？' },
    { role: 'user', content: '钱收了，鸡蛋没要。他说孩子那晚走三十里路，不容易。' },
    { role: 'assistant', content: '这话您当时听懂了吗？' },
    { role: 'user', content: '那会儿不懂，后来自己当了爹才懂。' },
    { role: 'assistant', content: '再后来呢？' },
    { role: 'user', content: '前年听说陈大夫不在了，我去送了他。' },
    { role: 'assistant', content: '站在那儿想起什么？' },
    { role: 'user', content: '想起那晚上那盏灯，还有他背药箱的背影。' },
    { role: 'assistant', content: '那盏灯对您意味着什么？' },
    { role: 'user', content: '意味着我爸多活了三十年，也让我知道什么叫有人在等你。' },
    { role: 'assistant', content: '今晚讲下来，心里怎么样？' },
    { role: 'user', content: '松快。这些年一直想跟人说，没人愿意听这么长的。' },
    { role: 'assistant', content: '我听着呢。要不要把它存下来，做成一段短片？' },
  ],
};

export const DEMO_SCRIPTS: DemoScript[] = [NIGHT_ROAD, RESERVOIR, SEWING_MACHINE];

/** 手动输入台词时用：去掉标点空白再比对。 */
function normalize(text: string): string {
  return (text || '').replace(/[\s，。、！？,.!?…~～"'“”‘’]/g, '');
}

/** 输入与某条脚本文案完全一致时，返回脚本里对应的下一句回答。 */
export function matchScriptReply(text: string): string | null {
  const target = normalize(text);
  if (!target) return null;
  for (const script of DEMO_SCRIPTS) {
    for (let i = 0; i < script.turns.length; i += 1) {
      const turn = script.turns[i];
      if (turn.role === 'user' && normalize(turn.content) === target) {
        const next = script.turns[i + 1];
        if (next?.role === 'assistant') return next.content;
      }
    }
  }
  return null;
}
