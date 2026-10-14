// ⚠️ 下面两个 declare module 会把 three 与 OrbitControls 的**真实类型覆盖成 any**，
//    等于对这两个模块关掉了全项目的类型检查。
//
//    实测证据：把本文件移走后 tsc 会报出 11 个真实错误 ——
//      HelixConstellationMode.ts  8 处：Material | Material[] 上不存在 dispose
//      RiverCruiseMode.ts         3 处：BufferGeometry 泛型协变、GLBufferAttribute 上无 array
//    现状：tsconfig 已装 @types/three，但环境声明的优先级更高，这些错误被静默压住。
//
//    待办（阶段 5）：删掉本文件并修掉那 11 处，而不是继续用 any 掩盖。
//    在修完之前保留本文件，否则 Vercel 构建会直接失败。
declare module 'three' {
  const THREE: any;
  export = THREE;
}

declare module 'three/examples/jsm/controls/OrbitControls.js' {
  const OrbitControls: any;
  export { OrbitControls };
}
