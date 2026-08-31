class CreateCatalogItems < ActiveRecord::Migration[8.1]
  def change
    create_table :catalog_items do |t|
      t.references :catalog, null: false, foreign_key: true

      # The media file's full key from the bucket root. SPEC makes this the
      # identity of an entry within a catalog.
      t.string :path, null: false

      # The sidecar's own `id`. Opaque per SPEC -- never parsed, never used as
      # a primary key here. Named to keep it distinct from this row's id.
      t.string :sidecar_id

      t.string :title
      # Deliberately a string. SPEC allows "YYYY-MM-DD" or a full RFC 3339
      # timestamp, and casting to a date would silently discard the difference
      # between "that day" and "that moment". Both forms sort correctly as
      # text, which is all the grid needs.
      t.string :recorded_at
      t.datetime :uploaded_at
      t.float :duration_s
      t.bigint :size_bytes
      t.string :media_type
      t.string :thumbnail

      # The complete sidecar, verbatim. SPEC requires unknown fields to survive
      # a round trip; keeping the whole object means this cache never becomes
      # the reason a field was lost.
      t.jsonb :sidecar, null: false, default: {}

      t.timestamps
    end

    add_index :catalog_items, [ :catalog_id, :path ], unique: true
    add_index :catalog_items, [ :catalog_id, :recorded_at ]
  end
end
