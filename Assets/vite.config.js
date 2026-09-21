import { defineConfig } from 'vite';

// 验证辅助插件：
// /__gate   —— 挂起响应直到收到 ready（或 10s 兜底），页面里有一张指向它的 <img>，
//              从而把 load 事件（即无头截图的捕获时机）推迟到场景就绪之后
// /__ready  —— 场景构建完成后由 main.js 调用，放行 gate
function sceneReadyGate() {
  return {
    name: 'scene-ready-gate',
    configureServer(server) {
      let ready = false;
      const waiters = new Set();
      server.middlewares.use((req, res, next) => {
        if (req.url.startsWith('/assets/environment/') || req.url === '/__ready' || req.url === '/__gate') {
          console.log(`[gate] ${req.method} ${req.url}`);
        }
        if (req.url === '/__ready') {
          ready = true;
          waiters.forEach((w) => w());
          waiters.clear();
          res.statusCode = 200;
          res.end('ok');
          return;
        }
        if (req.url === '/__gate') {
          let settled = false;
          const done = () => {
            if (settled) return;
            settled = true;
            waiters.delete(done);
            res.statusCode = 200;
            res.setHeader('content-type', 'image/gif');
            res.end(Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7', 'base64'));
          };
          if (ready) {
            done();
          } else {
            waiters.add(done);
            setTimeout(done, 10000); // 兜底：场景出错也不永久挂死
          }
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [sceneReadyGate()],
});
