-- migrate:up

-- Retention of subscription data (spec §5 `cleanup-subscriptions`, §11.1 #2 and #6):
-- - pending Subscriptions not confirmed within 7 days of the last request (`consent_at`),
-- - Subscriptions unsubscribed 30 or more days ago (their deliveries go with them),
-- - email_deliveries older than 12 months.
--
-- Least privilege: no role may DELETE from the private tables directly except ofa_web
-- (which needs it for "delete my data"). The daily job calls this function instead; it
-- takes no arguments, so a caller cannot widen what is deleted (e.g. by passing a future
-- date), and it reads nothing back but counts. Only ofa_mailer, the role of the
-- subscription jobs, may execute it.
CREATE FUNCTION cleanup_subscriptions()
RETURNS TABLE (pending_deleted bigint, unsubscribed_deleted bigint, deliveries_deleted bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    DELETE FROM public.email_deliveries WHERE sent_at < now() - interval '12 months';
    GET DIAGNOSTICS deliveries_deleted = ROW_COUNT;

    DELETE FROM public.subscriptions
    WHERE status = 'pending' AND consent_at < now() - interval '7 days';
    GET DIAGNOSTICS pending_deleted = ROW_COUNT;

    DELETE FROM public.subscriptions
    WHERE status = 'unsubscribed' AND unsubscribed_at <= now() - interval '30 days';
    GET DIAGNOSTICS unsubscribed_deleted = ROW_COUNT;

    RETURN NEXT;
END
$$;

REVOKE ALL ON FUNCTION cleanup_subscriptions() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cleanup_subscriptions() TO ofa_mailer;

-- migrate:down
DROP FUNCTION cleanup_subscriptions();
