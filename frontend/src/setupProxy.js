const { createProxyMiddleware } = require('http-proxy-middleware');
module.exports = app =>
  app.use('/api', createProxyMiddleware({ target: 'http://101.43.50.74:8000', changeOrigin: true }));
