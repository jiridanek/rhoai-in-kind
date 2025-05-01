import * as t from '@babel/types';
import traverse, { NodePath, Visitor, Scope, Binding } from '@babel/traverse';

// Helper to check if a node is the fromHere() call statement
function isFromHereStatement(node: t.Node): node is t.ExpressionStatement {
    return (
        t.isExpressionStatement(node) &&
        t.isCallExpression(node.expression) &&
        t.isIdentifier(node.expression.callee, { name: 'fromHere' }) &&
        node.expression.arguments.length === 0
    );
}

// Define the structure for the Babel plugin export
interface PluginDefinition {
    name: string;
    visitor: Visitor;
}

export default function ({ types }: { types: typeof t }): PluginDefinition {
    return {
        name: 'transform-from-here',
        visitor: {
            Function(path: NodePath<t.Function>) {
                const functionBodyPath = path.get('body');

                // Ensure we are working with a function that has a BlockStatement body
                if (!functionBodyPath.isBlockStatement()) {
                    const functionName = (t.isFunctionDeclaration(path.node) || t.isFunctionExpression(path.node))
                        ? path.node.id?.name
                        : null;
                    // console.warn(`Skipping function '${functionName ?? 'anonymous'}' as it does not have a block statement body.`);
                    return;
                }

                const bodyPaths: NodePath<t.Statement>[] = functionBodyPath.get('body');
                let fromHereIndex: number = -1;
                let fromHerePath: NodePath<t.Statement> | null = null;

                // --- Step 1: Find the fromHere() marker ---
                for (let i = 0; i < bodyPaths.length; i++) {
                    const currentPath = bodyPaths[i];
                    if (isFromHereStatement(currentPath.node)) {
                        if (fromHereIndex !== -1) {
                            throw currentPath.buildCodeFrameError(
                                'Multiple fromHere() calls found in the same function scope. Only one is allowed.'
                            );
                        }
                        fromHereIndex = i;
                        fromHerePath = currentPath;
                    }
                }

                // If no marker found, exit
                if (fromHereIndex === -1 || !fromHerePath) {
                    return;
                }

                // --- Step 2: Split statements ---
                const beforeStatementsPaths: NodePath<t.Statement>[] = bodyPaths.slice(0, fromHereIndex);
                const beforeStatementNodes = new Set(beforeStatementsPaths.map(p => p.node));
                const afterStatementsPaths: NodePath<t.Statement>[] = bodyPaths.slice(fromHereIndex + 1);

                // --- Step 3: Analyze variable usage AFTER fromHere() ---
                const usedVariableNames = new Set<string>();
                const afterStatementsBlock: t.BlockStatement = t.blockStatement(
                    afterStatementsPaths.map(p => p.node)
                );

                traverse(afterStatementsBlock, {
                    Identifier(identifierPath: NodePath<t.Identifier>) {
                        if (!identifierPath.isReferencedIdentifier()) {
                            return;
                        }
                        const identifierName = identifierPath.node.name;
                        const binding = path.scope.getBinding(identifierName);
                        if (binding && binding.scope === path.scope) {
                            let declarationStatementPath: NodePath | null = binding.path;
                            while (declarationStatementPath && !declarationStatementPath.isStatement()) {
                                declarationStatementPath = declarationStatementPath.parentPath;
                            }
                            if (declarationStatementPath && beforeStatementNodes.has(declarationStatementPath.node)) {
                                usedVariableNames.add(identifierName);
                            }
                        }
                    },
                    CallExpression(callPath: NodePath<t.CallExpression>) {
                        const callee = callPath.node.callee;
                        if (t.isIdentifier(callee) && callPath.get('callee').isReferencedIdentifier()) {
                            const calleeName = callee.name;
                            const binding = path.scope.getBinding(calleeName);
                            if (binding && binding.path.isFunctionDeclaration() && binding.scope === path.scope) {
                                const declarationStatementPath = binding.path;
                                if (beforeStatementNodes.has(declarationStatementPath.node)) {
                                    usedVariableNames.add(calleeName);
                                }
                            }
                        }
                    }
                }, path.scope, {}, functionBodyPath);


                // --- Step 4: Identify necessary declarations BEFORE fromHere() ---
                const necessaryDeclarationNodes: t.Statement[] = [];
                const addedDeclarations = new Set<t.Node>();

                beforeStatementsPaths.forEach(statementPath => {
                    let declarationNodeToAdd: t.Statement | null = null;

                    if (statementPath.isVariableDeclaration()) {
                        const necessaryDeclarators: t.VariableDeclarator[] = [];
                        statementPath.node.declarations.forEach(declarator => {
                            const identifiersMap = t.getBindingIdentifiers(declarator.id);
                            let declaratorNeeded = false;
                            Object.values(identifiersMap).flat().forEach((node: t.Node | null) => {
                                if (node && t.isIdentifier(node) && usedVariableNames.has(node.name)) {
                                    declaratorNeeded = true;
                                }
                            });
                            if (declaratorNeeded && !necessaryDeclarators.includes(declarator)) {
                                necessaryDeclarators.push(declarator);
                            }
                        });
                        if (necessaryDeclarators.length > 0) {
                            declarationNodeToAdd = t.variableDeclaration(
                                statementPath.node.kind,
                                necessaryDeclarators
                            );
                        }
                    }
                    else if (statementPath.isFunctionDeclaration()) {
                        if (statementPath.node.id && usedVariableNames.has(statementPath.node.id.name)) {
                            declarationNodeToAdd = statementPath.node;
                        }
                    }
                    // Add similar check for ClassDeclaration if needed
                    // else if (statementPath.isClassDeclaration()) { ... }

                    if (declarationNodeToAdd) {
                        if (!addedDeclarations.has(declarationNodeToAdd)) {
                            necessaryDeclarationNodes.push(declarationNodeToAdd);
                            addedDeclarations.add(declarationNodeToAdd);
                        }
                    }
                });

                // --- Step 5: Construct the new function body ---
                const newBodyStatements: t.Statement[] = [
                    ...necessaryDeclarationNodes,
                    ...afterStatementsPaths.map(p => p.node)
                ];

                // --- Step 6: Replace the body ---
                functionBodyPath.replaceWith(t.blockStatement(newBodyStatements));
            },
        },
    };
}
