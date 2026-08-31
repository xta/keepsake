<script setup>
import { Head, useForm } from '@inertiajs/vue3'
import AppLayout from '../../layouts/AppLayout.vue'
defineOptions({ layout: AppLayout })

const props = defineProps({ token: String })
const form = useForm({ password: '', password_confirmation: '' })
</script>

<template>
  <Head title="Choose a new password" />
  <div style="max-width: 24rem; margin: 2rem auto;">
    <h1>Choose a new password</h1>
    <form class="card card-pad" style="margin-top: 1.5rem"
          @submit.prevent="form.patch(`/passwords/${token}`)">
      <div class="field">
        <label for="password">New password</label>
        <input id="password" v-model="form.password" type="password" autocomplete="new-password" required autofocus />
      </div>
      <div class="field">
        <label for="confirm">Confirm password</label>
        <input id="confirm" v-model="form.password_confirmation" type="password" autocomplete="new-password" required />
      </div>
      <button class="btn btn-primary" style="width: 100%" :disabled="form.processing">Save password</button>
    </form>
  </div>
</template>
