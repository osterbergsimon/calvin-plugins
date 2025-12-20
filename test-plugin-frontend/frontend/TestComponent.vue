<template>
  <div class="test-plugin-frontend">
    <h3>Test Plugin with Frontend</h3>
    <p>{{ message }}</p>
  </div>
</template>

<script>
export default {
  name: "TestComponent",
  props: {
    message: {
      type: String,
      default: "Hello from test plugin with frontend!",
    },
  },
};
</script>

<style scoped>
.test-plugin-frontend {
  padding: 1rem;
  text-align: center;
}
</style>

