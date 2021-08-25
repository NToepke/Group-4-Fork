BEGIN; 

ALTER TABLE "augur_data"."pull_request_message_ref" ADD CONSTRAINT "pr-comment-nk" UNIQUE ("pr_message_ref_src_comment_id", "tool_source");

ALTER TABLE "augur_data"."pull_request_review_message_ref" ADD CONSTRAINT "pr-review-nk" UNIQUE ("pr_review_msg_src_id", "tool_source");

ALTER TABLE "augur_data"."pull_request_reviewers" ADD COLUMN "repo_id" int8;

ALTER TABLE "augur_data"."pull_request_reviews" DROP CONSTRAINT "fk_pull_request_reviews_pull_requests_1";

ALTER TABLE "augur_data"."pull_request_reviews" DROP CONSTRAINT "fk_pull_request_reviews_contributors_1";

ALTER TABLE "augur_data"."pull_request_reviews" ADD COLUMN "repo_id" int8;

ALTER TABLE "augur_data"."pull_request_reviews" ADD CONSTRAINT "sourcepr-review-id" UNIQUE ("pr_review_src_id", "tool_source");

COMMENT ON CONSTRAINT "sourcepr-review-id" ON "augur_data"."pull_request_reviews" IS 'Natural Key from Source, plus tool source to account for different platforms like GitHub and gitlab. ';

ALTER TABLE "augur_data"."pull_request_reviews" ADD CONSTRAINT "fk_pull_request_reviews_contributors_1" FOREIGN KEY ("cntrb_id") REFERENCES "augur_data"."contributors" ("cntrb_id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "augur_data"."pull_request_reviews" ADD CONSTRAINT "fk_pull_request_reviews_pull_requests_1" FOREIGN KEY ("pull_request_id") REFERENCES "augur_data"."pull_requests" ("pull_request_id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "augur_data"."pull_request_reviews" ADD CONSTRAINT "fk_repo_review" FOREIGN KEY ("repo_id") REFERENCES "augur_data"."repo" ("repo_id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "augur_data"."issue_message_ref" ADD CONSTRAINT "fk_repo_id_fk1" FOREIGN KEY ("repo_id") REFERENCES "augur_data"."repo" ("repo_id") ON DELETE RESTRICT ON UPDATE CASCADE;

update "augur_operations"."augur_settings" set value = 67 where setting = 'augur_data_version';


COMMIT; 

