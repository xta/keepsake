class CreateCatalogs < ActiveRecord::Migration[8.1]
  # A parsed copy of one bucket's index.json.
  #
  # CACHE, NEVER SOURCE OF TRUTH. The bucket is the system (SPEC.md: "No
  # external datastore"). Drop this table, refetch, and nothing is lost. It
  # exists only so the grid can sort and paginate without re-parsing the whole
  # catalog inside a request.
  def change
    create_table :catalogs do |t|
      t.references :library, null: false, foreign_key: true, index: { unique: true }

      # From the document itself.
      t.datetime :generated_at
      t.integer :item_count, null: false, default: 0
      t.bigint :total_bytes, null: false, default: 0

      # For conditional refetch: an unchanged catalog costs one 304.
      t.string :etag
      t.datetime :fetched_at, null: false

      t.timestamps
    end
  end
end
