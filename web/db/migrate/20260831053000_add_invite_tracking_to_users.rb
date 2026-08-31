class AddInviteTrackingToUsers < ActiveRecord::Migration[8.1]
  def change
    add_reference :users, :invited_by, foreign_key: { to_table: :users }
    add_column :users, :invited_at, :datetime
  end
end
