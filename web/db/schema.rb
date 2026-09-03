# This file is auto-generated from the current state of the database. Instead
# of editing this file, please use the migrations feature of Active Record to
# incrementally modify your database, and then regenerate this schema definition.
#
# This file is the source Rails uses to define your schema when running `bin/rails
# db:schema:load`. When creating a new database, `bin/rails db:schema:load` tends to
# be faster and is potentially less error prone than running all of your
# migrations from scratch. Old migrations may fail to apply correctly if those
# migrations use external dependencies or application code.
#
# It's strongly recommended that you check this file into your version control system.

ActiveRecord::Schema[8.1].define(version: 2026_09_03_065100) do
  # These are extensions that must be enabled in order to support this database
  enable_extension "pg_catalog.plpgsql"

  create_table "catalog_items", force: :cascade do |t|
    t.bigint "catalog_id", null: false
    t.datetime "created_at", null: false
    t.float "duration_s"
    t.string "media_type"
    t.string "path", null: false
    t.string "recorded_at"
    t.jsonb "sidecar", default: {}, null: false
    t.string "sidecar_id"
    t.bigint "size_bytes"
    t.string "thumbnail"
    t.string "title"
    t.datetime "updated_at", null: false
    t.datetime "uploaded_at"
    t.index ["catalog_id", "path"], name: "index_catalog_items_on_catalog_id_and_path", unique: true
    t.index ["catalog_id", "recorded_at"], name: "index_catalog_items_on_catalog_id_and_recorded_at"
    t.index ["catalog_id"], name: "index_catalog_items_on_catalog_id"
  end

  create_table "catalogs", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.string "etag"
    t.datetime "fetched_at", null: false
    t.datetime "generated_at"
    t.integer "item_count", default: 0, null: false
    t.bigint "library_id", null: false
    t.bigint "total_bytes", default: 0, null: false
    t.datetime "updated_at", null: false
    t.index ["library_id"], name: "index_catalogs_on_library_id", unique: true
  end

  create_table "invites", force: :cascade do |t|
    t.datetime "claimed_at"
    t.bigint "claimed_by_id"
    t.datetime "created_at", null: false
    t.bigint "created_by_id"
    t.string "email_address"
    t.datetime "expires_at", null: false
    t.bigint "organization_id"
    t.string "token", null: false
    t.datetime "updated_at", null: false
    t.index ["claimed_by_id"], name: "index_invites_on_claimed_by_id"
    t.index ["created_by_id"], name: "index_invites_on_created_by_id"
    t.index ["organization_id"], name: "index_invites_on_organization_id"
    t.index ["token"], name: "index_invites_on_token", unique: true
  end

  create_table "libraries", force: :cascade do |t|
    t.string "access_key_id", null: false
    t.string "access_level", default: "read_only", null: false
    t.string "bucket", null: false
    t.datetime "created_at", null: false
    t.bigint "created_by_id"
    t.string "endpoint", null: false
    t.boolean "force_path_style", default: false, null: false
    t.string "label", null: false
    t.text "last_error"
    t.datetime "last_verified_at"
    t.bigint "organization_id", null: false
    t.string "prefix"
    t.string "provider", null: false
    t.string "region", null: false
    t.text "secret_access_key", null: false
    t.datetime "sweep_finished_at"
    t.string "sweep_message"
    t.datetime "sweep_started_at"
    t.string "sweep_state"
    t.datetime "updated_at", null: false
    t.index ["created_by_id"], name: "index_libraries_on_created_by_id"
    t.index ["organization_id", "label"], name: "index_libraries_on_organization_id_and_label", unique: true
    t.index ["organization_id"], name: "index_libraries_on_organization_id"
  end

  create_table "organizations", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.string "name", null: false
    t.datetime "updated_at", null: false
  end

  create_table "sessions", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.string "ip_address"
    t.datetime "last_active_at", null: false
    t.datetime "updated_at", null: false
    t.string "user_agent"
    t.bigint "user_id", null: false
    t.index ["last_active_at"], name: "index_sessions_on_last_active_at"
    t.index ["user_id"], name: "index_sessions_on_user_id"
  end

  create_table "users", force: :cascade do |t|
    t.datetime "created_at", null: false
    t.string "email_address", null: false
    t.datetime "invited_at"
    t.bigint "invited_by_id"
    t.bigint "organization_id", null: false
    t.string "password_digest", null: false
    t.datetime "updated_at", null: false
    t.index ["email_address"], name: "index_users_on_email_address", unique: true
    t.index ["invited_by_id"], name: "index_users_on_invited_by_id"
    t.index ["organization_id"], name: "index_users_on_organization_id"
  end

  add_foreign_key "catalog_items", "catalogs"
  add_foreign_key "catalogs", "libraries"
  add_foreign_key "invites", "organizations"
  add_foreign_key "invites", "users", column: "claimed_by_id"
  add_foreign_key "invites", "users", column: "created_by_id"
  add_foreign_key "libraries", "organizations"
  add_foreign_key "libraries", "users", column: "created_by_id"
  add_foreign_key "sessions", "users"
  add_foreign_key "users", "organizations"
  add_foreign_key "users", "users", column: "invited_by_id"
end
