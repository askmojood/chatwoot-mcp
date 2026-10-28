# Applied inside the Chatwoot container after seeding (scripts/reset.sh): Chatwoot's API stamps everything "now",
# so this moves each message to the hours given in docker/backdate.json, credits agents' messages to the assignee,
# and refreshes the conversation's activity and waiting times from them.
JSON.parse(STDIN.read).each do |row|
  conv = Conversation.find(row['conversation'])
  row['messages'].each_with_index do |id, i|
    at = row['hours'][i].hours.ago
    cols = { created_at: at, updated_at: at }
    cols[:sender_id] = row['senders'][i] if row['senders'][i]
    Message.where(id: id).update_all(cols)
  end
  msgs = conv.messages.where(id: row['messages']).order(:created_at).to_a
  # Chatwoot's own activity lines ("Assigned to … by …", "marked resolved") belong near the start, or the end.
  conv.messages.where(message_type: :activity).each do |m|
    late = m.content =~ /resolved|pending|snoozed/i
    at = late ? msgs.last.created_at + 2.minutes : msgs.first.created_at + 2.minutes
    m.update_columns(created_at: at, updated_at: at)
  end
  last_in = msgs.select(&:incoming?).map(&:created_at).max
  last_out = msgs.select { |m| m.outgoing? && !m.private }.map(&:created_at).max
  first_out = msgs.select { |m| m.outgoing? && !m.private }.map(&:created_at).min
  waiting = last_in && (last_out.nil? || last_in > last_out) ? msgs.select(&:incoming?).reject { |m| last_out && m.created_at < last_out }.map(&:created_at).min : nil
  conv.update_columns(created_at: msgs.first.created_at, last_activity_at: msgs.last.created_at,
                      updated_at: msgs.last.created_at, waiting_since: (conv.open? ? waiting : nil),
                      first_reply_created_at: first_out)
end
puts 'backdated'
