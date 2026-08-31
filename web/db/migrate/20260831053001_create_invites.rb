class CreateInvites < ActiveRecord::Migration[8.1]
  def change
    create_table :invites do |t|
      t.string :token, null: false
      # Optional: an invite may name the address it was minted for, but claiming
      # does not require matching it. Pinning the address would mean a typo
      # burns the invite.
      t.string :email_address

      # Nullable on purpose: the first invite on a fresh install is minted by
      # the system, before any user exists. A placeholder user would be a lie
      # in the audit trail.
      t.references :created_by, foreign_key: { to_table: :users }
      t.references :claimed_by, foreign_key: { to_table: :users }
      t.datetime :claimed_at
      t.datetime :expires_at, null: false

      t.timestamps
    end

    add_index :invites, :token, unique: true
  end
end
