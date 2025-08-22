export default {
  esbuild: {
    external: ['node-fetch', '@modelcontextprotocol/sdk', 'proper-lockfile'],
    minify: true,
    target: 'node20',
    format: 'esm',
  },
};
