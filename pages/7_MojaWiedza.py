import streamlit.components.v1 as components

components.html("""
<script>
  const link = document.createElement('link');
  link.rel = 'manifest';
  link.href = '/app/static/manifest.json';
  window.parent.document.head.appendChild(link);
</script>
""", height=0)
