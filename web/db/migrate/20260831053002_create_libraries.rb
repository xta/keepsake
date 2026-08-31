class CreateLibraries < ActiveRecord::Migration[8.1]
  def change
    create_table :libraries do |t|
      t.references :user, null: false, foreign_key: true
      t.string :label, null: false

      # Connection. `provider` selects a preset that builds `endpoint` from
      # region or account id; "other" is the only mode taking a free-form URL.
      t.string :provider, null: false
      t.string :endpoint, null: false
      t.string :region, null: false
      t.string :bucket, null: false
      # Optional key prefix, for a keepsake library living under a subpath
      # rather than at the bucket root.
      t.string :prefix
      t.boolean :force_path_style, null: false, default: false

      # Declared by the user, not discovered. Gates the v2 sweep, which writes.
      t.string :access_level, null: false, default: "read_only"

      t.string :access_key_id, null: false
      # Encrypted at rest (non-deterministic), so this holds ciphertext and
      # must be text rather than a bounded string.
      t.text :secret_access_key, null: false

      # Result of the last "Test connection", so a broken library says why on
      # its own settings page instead of rendering an empty grid.
      t.datetime :last_verified_at
      t.text :last_error

      t.timestamps
    end

    add_index :libraries, [ :user_id, :label ], unique: true
  end
end
